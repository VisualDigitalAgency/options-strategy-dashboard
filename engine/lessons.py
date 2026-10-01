"""Lessons and quizzes for the learning path (issue #124, part of #120).

Content lives in content/lessons/ as a pair per lesson: `NN-slug.md` (the body, a small markdown
subset the frontend renders without HTML) and `NN-slug.json` (title, level, order, summary and the
quiz). It is reviewed through pull requests like code, so nothing reaches users unapproved.

Reading lessons is public, so lesson pages can be found and shared without an account. Quizzes need
a sign-in: answers are checked here and never sent to the browser. A pass (>= PASS_PCT) is recorded
once in `lesson_progress`, which the XP ledger (#122) will read. After a failed attempt the quiz
locks for RETRY_HOURS. Quizzes unlock in course order (#161): one can be taken only once the lesson
before it is passed (or it was passed already).
"""

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from . import db

LESSON_DIR = Path(__file__).resolve().parent.parent / "content" / "lessons"
PASS_PCT = 80
RETRY_HOURS = 24


class LessonError(ValueError):
    pass


@lru_cache(maxsize=1)
def _load() -> dict:
    """slug -> lesson. Read once per process; content only changes with a deploy."""
    out = {}
    for meta_path in sorted(LESSON_DIR.glob("*.json")):
        slug = meta_path.stem.split("-", 1)[1]
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = meta_path.with_suffix(".md").read_text(encoding="utf-8")
        for q in meta["questions"]:
            if not 0 <= q["answer"] < len(q["options"]):
                raise RuntimeError(f"lesson {slug}: answer index out of range in {q['q']!r}")
        out[slug] = {**meta, "slug": slug, "body": body}
    return out


def _lesson(slug: str) -> dict:
    lesson = _load().get(slug)
    if lesson is None:
        raise LessonError("Lesson not found")
    return lesson


def list_lessons() -> list[dict]:
    """Every lesson's card data, in course order (level, then order)."""
    rows = [{k: l[k] for k in ("slug", "title", "level", "order", "summary", "minutes")} | {"questions": len(l["questions"])}
            for l in _load().values()]
    return sorted(rows, key=lambda r: (r["level"], r["order"]))


def get_lesson(slug: str) -> dict:
    """One lesson with its quiz questions and options, but never the answers."""
    l = _lesson(slug)
    order = list_lessons()
    i = next(n for n, r in enumerate(order) if r["slug"] == slug)
    return {
        **{k: l[k] for k in ("slug", "title", "level", "order", "summary", "minutes", "body")},
        "questions": [{"q": q["q"], "options": q["options"]} for q in l["questions"]],
        "prev": order[i - 1]["slug"] if i > 0 else None,
        "next": order[i + 1]["slug"] if i + 1 < len(order) else None,
    }


def progress(user_id: int) -> list[dict]:
    """The caller's quiz record per lesson: attempts, best score, when it was passed, and when a
    failed quiz can be retaken."""
    with db.tx(user_id) as c:
        return c.all("SELECT slug, attempts, best_score, passed_at, last_attempt_at, retry_at "
                     "FROM lesson_progress WHERE user_id=:u", u=user_id)


def submit_quiz(user_id: int, slug: str, answers: list) -> dict:
    """Scores one attempt. Returns the score, whether it passed, and per question whether it was
    right with the explanation. A failed attempt locks the quiz for RETRY_HOURS; after a pass the
    quiz can be retaken freely, but only the first pass counts."""
    l = _lesson(slug)
    qs = l["questions"]
    if len(answers) != len(qs) or not all(isinstance(a, int) and not isinstance(a, bool) for a in answers):
        raise LessonError(f"Answer all {len(qs)} questions")
    now = datetime.now(timezone.utc)
    with db.tx(user_id) as c:
        row = c.one("SELECT passed_at, retry_at > now() AS locked FROM lesson_progress "
                    "WHERE user_id=:u AND slug=:s FOR UPDATE", u=user_id, s=slug)
        prev = get_lesson(slug)["prev"]
        if prev and not (row and row["passed_at"]) and not c.value(
                "SELECT 1 FROM lesson_progress WHERE user_id=:u AND slug=:s AND passed_at IS NOT NULL", u=user_id, s=prev):
            raise LessonError(f"Pass \"{_lesson(prev)['title']}\" first to unlock this quiz")
        if row and not row["passed_at"] and row["locked"]:
            raise LessonError("You can retake this quiz 24 hours after your last attempt")
        right = [a == q["answer"] for a, q in zip(answers, qs)]
        score = round(100 * sum(right) / len(qs))
        passed = score >= PASS_PCT
        first_pass = passed and not (row and row["passed_at"])
        retry_at = None if passed or (row and row["passed_at"]) else now + timedelta(hours=RETRY_HOURS)
        c.run("INSERT INTO lesson_progress (user_id, slug, attempts, best_score, passed_at, last_attempt_at, retry_at) "
              "VALUES (:u, :s, 1, :sc, CASE WHEN :p THEN now() END, now(), :r) "
              "ON CONFLICT (user_id, slug) DO UPDATE SET attempts = lesson_progress.attempts + 1, "
              "best_score = GREATEST(lesson_progress.best_score, :sc), "
              "passed_at = COALESCE(lesson_progress.passed_at, CASE WHEN :p THEN now() END), "
              "last_attempt_at = now(), retry_at = :r",
              u=user_id, s=slug, sc=score, p=passed, r=retry_at)
    return {"score": score, "passed": passed, "first_pass": first_pass, "pass_pct": PASS_PCT,
            "retry_at": retry_at.isoformat() if retry_at else None,
            # The right option is revealed only on a pass, so a failed attempt can't just be copied next time.
            "results": [{"correct": ok, "why": q["why"], **({"answer": q["answer"]} if passed else {})}
                        for ok, q in zip(right, qs)]}
