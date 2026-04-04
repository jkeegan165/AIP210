print("RUNNING FILE:", __file__)

from flask import Flask, render_template, request, session, jsonify, send_file
import random, time, tempfile
import json

GLOBAL_QUESTION_BANK = []
LAST_RESULTS = {}

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "aip210_secret"

TIME_LIMIT = 7200


# ================= QUESTION BANK =================
def build_question_bank():
    base = [
        {
            "prompt": "A fraud detection model shows high accuracy but misses fraud cases.",
            "options": ["Overfitting", "Class imbalance", "Bias", "Variance"],
            "answer": "Class imbalance",
            "domain": "Metrics",
            "explanation": "Accuracy fails with imbalanced data."
        },
        {
            "prompt": "Precision is high but recall is low.",
            "options": ["Few false positives", "Few false negatives", "Balanced", "Overfitting"],
            "answer": "Few false positives",
            "domain": "Metrics",
            "explanation": "Precision penalizes false positives."
        },
        {
            "prompt": "Which model is least affected by scaling?",
            "options": ["KNN", "SVM", "Decision Tree", "Logistic Regression"],
            "answer": "Decision Tree",
            "domain": "Model Behavior",
            "explanation": "Trees don’t depend on magnitude."
        },
        {
            "prompt": "Model performs well in training but poorly in test.",
            "options": ["Underfitting", "Overfitting", "Drift", "Noise"],
            "answer": "Overfitting",
            "domain": "Model Behavior",
            "explanation": "Model memorized training data."
        }
    ]

    contexts = [
        "In a healthcare system,",
        "In a fraud detection system,",
        "In a financial model,",
        "In a recommendation engine,"
    ]

    phrasings = [
        "What is the issue?",
        "What is the cause?",
        "What explains this?",
    ]

    bank = []
    for q in base:
        for c in contexts:
            for p in phrasings:
                new_q = q.copy()
                new_q["prompt"] = f"{c} {q['prompt']} {p}"
                bank.append(new_q)

    random.shuffle(bank)
    return bank
def load_json_questions():
    '''
    with open("questions.json", "r", encoding="utf-8") as f:
    '''
    import os

    file_path = os.path.join(os.path.dirname(__file__), "questions.json")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_questions = data.get("questions", [])
    bank = []

    for q in raw_questions:
        try:
            prompt = q["question"]
            options = q["options"]
            answer_index = q["answer_index"]
            answer = options[answer_index]

            bank.append({
                "prompt": prompt,
                "options": options,
                "answer": answer,
                "domain": q.get("domain", {}).get("name", "General"),
                "difficulty": q.get("difficulty", "medium"),
                "explanation": q.get("explanation", ""),
                "concept": prompt[:80].lower()
            })

        except Exception as e:
            print("Skipping bad question:", e)

    return bank
def dedupe_questions(bank):
    seen = set()
    unique = []

    for q in bank:
        key = q["prompt"].strip().lower()

        if key not in seen:
            seen.add(key)
            unique.append(q)

    return unique

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start")
def start():
    print("🔥 START ROUTE HIT 🔥")

    session.clear()

    bank = load_json_questions()
    bank = dedupe_questions(bank)

    print("TOTAL LOADED QUESTIONS:", len(bank))

    if not bank:
        bank = build_question_bank()

    random.shuffle(bank)

    global GLOBAL_QUESTION_BANK
    GLOBAL_QUESTION_BANK = bank

    # 🎯 CONFIG
    NUM_QUESTIONS = 50

    # 🎯 GROUP QUESTIONS BY DOMAIN (SAFE VERSION)
    domain_groups = {}

    for i, q in enumerate(bank):

        domain_field = q.get("domain", {})

        if isinstance(domain_field, dict):
            domain_name = domain_field.get("name", "General")
        else:
            domain_name = str(domain_field)

        if domain_name not in domain_groups:
            domain_groups[domain_name] = []

        domain_groups[domain_name].append(i)

    # 🔀 Shuffle each domain group
    for d in domain_groups:
        random.shuffle(domain_groups[d])

    # 📊 Determine distribution
    num_domains = len(domain_groups)
    base_per_domain = NUM_QUESTIONS // num_domains
    remainder = NUM_QUESTIONS % num_domains

    selected_indexes = []

    # 🎯 Select balanced questions
    for i, (domain, idx_list) in enumerate(domain_groups.items()):
        take = base_per_domain + (1 if i < remainder else 0)
        selected_indexes.extend(idx_list[:take])

    # 🔀 Final shuffle for randomness
    random.shuffle(selected_indexes)

    # ✅ STORE IN SESSION
    session["bank_indexes"] = selected_indexes
    session["idx"] = 0
    session["answers"] = {}
    session["start_time"] = time.time()

    return jsonify(success=True)
@app.route("/question")
def question():
    indexes = session.get("bank_indexes", [])
    idx = session.get("idx", 0)

    # ✅ SAFETY CHECK (prevents crash)
    if not indexes:
        return jsonify(error="No exam started")

    # ✅ DONE CONDITION
    if idx >= len(indexes):
        return jsonify(done=True)

    # ✅ TIME CALCULATION
    elapsed = time.time() - session.get("start_time", time.time())

    pause_start = session.get("pause_start")
    pause_duration = session.get("pause_duration", 0)

    if pause_start:
        paused_elapsed = min(time.time() - pause_start, pause_duration)
        elapsed -= paused_elapsed

    remaining = TIME_LIMIT - elapsed
    remaining = max(0, int(remaining))

    # ✅ GET QUESTION
    q = GLOBAL_QUESTION_BANK[indexes[idx]]

    return jsonify(
        q=q,
        idx=idx,
        total=len(indexes),
        remaining=remaining,
        answers=session.get("answers", {}),
        flagged=session.get("flagged", [])
    )

@app.route("/answer", methods=["POST"])
def answer():
    try:
        data = request.get_json(silent=True) or {}

        # ✅ Safe session reads
        idx = int(session.get("idx", 0))
        indexes = session.get("bank_indexes", [])
        answers = session.get("answers", {})

        if not isinstance(answers, dict):
            answers = {}

        user_answer = data.get("answer")
        if user_answer is None:
            return jsonify(success=False, error="No answer provided")

        # ✅ Save answer
        answers[str(idx)] = user_answer
        session["answers"] = answers

        # ✅ Remove flag if answered
        flagged = session.get("flagged", [])
        if idx in flagged:
            flagged.remove(idx)
        session["flagged"] = flagged

        # 🔁 Find next unanswered question
        next_idx = None
        for i in range(idx + 1, len(indexes)):
            if str(i) not in answers:
                next_idx = i
                break

        # ✅ Move index forward correctly
        if next_idx is None:
            all_answered = all(str(i) in answers for i in range(len(indexes)))
            if all_answered:
                session["idx"] = len(indexes)
            else:
                session["idx"] = idx
        else:
            session["idx"] = next_idx

        session.modified = True

        return jsonify(success=True)

    except Exception as e:
        print("🔥 ERROR IN /answer:", e)
        return jsonify(success=False, error=str(e)), 500

@app.route("/flag", methods=["POST"])
def flag():
    idx = session.get("idx", 0)
    flagged = session.get("flagged", [])

    if idx not in flagged:
        flagged.append(idx)

    session["flagged"] = flagged

    # Track furthest progress
    session["current_max"] = max(session.get("current_max", 0), idx)

    # Move forward
    session["idx"] = idx + 1

    return jsonify(success=True, flagged=flagged)

@app.route("/goto/<int:i>")
def goto(i):
    session["idx"] = i
    return jsonify(success=True)


@app.route("/score")
def score():
    indexes = session["bank_indexes"]
    bank = [GLOBAL_QUESTION_BANK[i] for i in indexes]
    answers = session["answers"]

    results = []
    correct = 0

    domain_stats = {}

    for i, q in enumerate(bank):
        user = answers.get(str(i))
        is_correct = user == q["answer"]

        if is_correct:
            correct += 1

        domain = q.get("domain", "General")

        # Initialize domain tracking
        if domain not in domain_stats:
            domain_stats[domain] = {"correct": 0, "total": 0}

        domain_stats[domain]["total"] += 1
        if is_correct:
            domain_stats[domain]["correct"] += 1

        results.append({
            "question": q["prompt"],
            "options": q["options"],
            "correct": q["answer"],
            "user": user,
            "explanation": q["explanation"],
            "is_correct": is_correct,
            "domain": domain
        })

    # Convert to percentages
    domain_performance = []
    for d, stats in domain_stats.items():
        percent = int((stats["correct"] / stats["total"]) * 100)
        domain_performance.append({
            "domain": d,
            "score": percent,
            "correct": stats["correct"],
            "total": stats["total"]
        })

    # Sort weakest first
    domain_performance.sort(key=lambda x: x["score"])

    return jsonify(
        score=correct,
        total=len(bank),
        results=results,
        domains=domain_performance
    )

@app.route("/pause", methods=["POST"])
def pause():
    # Allow only one pause
    if session.get("pause_used", False):
        return jsonify(success=False, message="Pause already used")

    session["pause_used"] = True
    session["pause_start"] = time.time()
    session["pause_duration"] = 300  # 5 minutes

    return jsonify(success=True)

@app.route("/save", methods=["POST"])
def save_session():
    import json

    data = {
        "bank_indexes": session.get("bank_indexes"),
        "idx": session.get("idx"),
        "answers": session.get("answers"),
        "flagged": session.get("flagged"),
        "start_time": session.get("start_time"),
        "pause_used": session.get("pause_used"),
        "pause_start": session.get("pause_start"),
        "pause_duration": session.get("pause_duration")
    }

    with open("saved_session.json", "w") as f:
        json.dump(data, f)

    return jsonify(success=True)

@app.route("/resume")
def resume_session():
    import json
    import os

    if not os.path.exists("saved_session.json"):
        return jsonify(success=False)

    with open("saved_session.json", "r") as f:
        data = json.load(f)

    session.update(data)

    # 🔥 REBUILD QUESTION BANK
    bank = load_json_questions()
    bank = dedupe_questions(bank)

    global GLOBAL_QUESTION_BANK
    GLOBAL_QUESTION_BANK = bank

    # 🔥 CRITICAL FIX: ensure idx is valid
    session["idx"] = int(session.get("idx", 0))

    return jsonify(success=True)

@app.route("/start_weak")
def start_weak_exam():

    session.clear()

    # 🔹 Load and prepare bank
    bank = load_json_questions()
    bank = dedupe_questions(bank)

    if not bank:
        bank = build_question_bank()

    # 🔹 Get last results (already stored)
    global LAST_RESULTS
    domains = LAST_RESULTS.get("domains", [])

    if not domains:
        return jsonify(success=False, message="No prior results")

    # 🔥 Pick weakest 2 domains
    domains.sort(key=lambda x: x["score"])
    weakest = [d["domain"] for d in domains[:2]]

    print("WEAK DOMAINS:", weakest)

    # 🔹 Filter questions by weak domains
    filtered_indexes = [
        i for i, q in enumerate(bank)
        if str(q.get("domain", "General")) in weakest
    ]

    if not filtered_indexes:
        return jsonify(success=False, message="No weak domain questions found")

    # 🔹 Shuffle and limit
    import random
    random.shuffle(filtered_indexes)

    NUM_QUESTIONS = min(30, len(filtered_indexes))
    selected_indexes = filtered_indexes[:NUM_QUESTIONS]

    # 🔹 Store globally
    global GLOBAL_QUESTION_BANK
    GLOBAL_QUESTION_BANK = bank

    # 🔹 Initialize session
    session["bank_indexes"] = selected_indexes
    session["idx"] = 0
    session["answers"] = {}
    session["flagged"] = []
    session["start_time"] = time.time()

    return jsonify(success=True, domains=weakest)
@app.route("/results_page")
def results_page():
    global LAST_RESULTS

    return render_template(
        "results.html",
        score=LAST_RESULTS.get("score", 0),
        total=LAST_RESULTS.get("total", 0),
        percent=LAST_RESULTS.get("percent", 0),
        domains=LAST_RESULTS.get("domains", [])
    )

@app.route("/flashcards")
def flashcards():
    import json

    with open("flashcards.json", "r") as f:
        data = json.load(f)
        cards = data.get("flashcards", [])

    return render_template("flashcards.html", cards=cards)

@app.route("/store_results")
def store_results():
    global LAST_RESULTS

    indexes = session.get("bank_indexes", [])
    answers = session.get("answers", {})

    bank = [GLOBAL_QUESTION_BANK[i] for i in indexes]

    correct = 0
    domain_stats = {}

    for i, q in enumerate(bank):
        user = answers.get(str(i))
        is_correct = user == q["answer"]

        if is_correct:
            correct += 1

        domain = q.get("domain", "General")

        if domain not in domain_stats:
            domain_stats[domain] = {"correct": 0, "total": 0}

        domain_stats[domain]["total"] += 1
        if is_correct:
            domain_stats[domain]["correct"] += 1

    domains = []
    for d, stats in domain_stats.items():
        percent = int((stats["correct"] / stats["total"]) * 100)
        domains.append({"domain": d, "score": percent})

    percent = int((correct / len(bank)) * 100) if bank else 0

    LAST_RESULTS = {
        "score": correct,
        "total": len(bank),
        "percent": percent,
        "domains": domains
    }

    return jsonify(success=True)

@app.route("/download_pdf")
def download_pdf():
    import tempfile

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    filename = tmp.name
    tmp.close()

    indexes = session.get("bank_indexes", [])
    answers = session.get("answers", {})

    bank = [GLOBAL_QUESTION_BANK[i] for i in indexes]

    doc = SimpleDocTemplate(filename)
    styles = getSampleStyleSheet()

    content = []

    score = 0

    # --- Build content ---
    for i, q in enumerate(bank):
        user = answers.get(str(i), "N/A")
        correct = q["answer"]

        # Determine correctness
        if user == correct:
            user_color = "green"
            score += 1
        else:
            user_color = "red"

        # Question
        content.append(Paragraph(f"<b>Q{i+1}:</b> {q['prompt']}", styles["Normal"]))
        content.append(Spacer(1, 6))

        # User answer (colored)
        content.append(Paragraph(
            f"Your Answer: <font color='{user_color}'>{user}</font>",
            styles["Normal"]
        ))

        # Correct answer (always green)
        content.append(Paragraph(
            f"Correct Answer: <font color='green'>{correct}</font>",
            styles["Normal"]
        ))

        content.append(Spacer(1, 6))

        # Explanation (if exists)
        if q.get("explanation"):
            content.append(Paragraph(
                f"Explanation: {q['explanation']}",
                styles["Normal"]
            ))
            content.append(Spacer(1, 10))

        content.append(Spacer(1, 12))

    # --- Add score at top ---
    percent = int((score / len(bank)) * 100) if bank else 0

    content.insert(0, Paragraph(
        f"<b>Score: {score}/{len(bank)} ({percent}%)</b>",
        styles["Title"]
    ))
    content.insert(1, Spacer(1, 12))

    # --- Build PDF ---
    doc.build(content)

    return send_file(filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)