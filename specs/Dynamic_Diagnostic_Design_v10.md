# The AML Dynamic Diagnostic

### A plain-language design guide

**Version 10 (engine 0.10.0) | July 2026**

## 1. What it is, in one paragraph

The dynamic diagnostic is a short, smart test that works out which maths skills a learner already understands and which they still need to work on. It does this by choosing each question based on how the learner has answered so far, rather than giving every learner the same fixed list of questions. The goal is to place each learner at the right starting point across four arithmetic operations: addition, subtraction, multiplication, and division.

It replaces the **static diagnostic** we use today (the fixed-question test used in Delhi in April and May 2026), which asks every learner the same questions regardless of their answers.

A few words we will use throughout:

- **Skill:** the smallest unit the diagnostic measures, for example “2-digit addition with carry.” There are 39 such skills in the Delhi scope (40 across all tenants).

- **Mastery:** whether a learner has reliably learned a skill.

- **Verdict:** the diagnostic’s conclusion about a learner and a skill (for example, “confident this learner has mastered this skill”).

- **MainD:** the deeper main diagnostic inside AML that a learner takes when they start work on a skill. It has roughly 5 to 12 questions per skill. If the dynamic diagnostic is already confident a learner has mastered a skill, the learner can skip that skill’s MainD.

## 2. What the diagnostic is trying to do

Two things, at once:

- **Reach the right conclusion about each of the learner’s skills** using as few questions as the evidence allows.

- **Know how sure it is about the learner.** Rather than forcing a yes or no on every skill, it says “confident” only when it has enough evidence about that learner, and says “uncertain” when it does not.

The second point is what makes it trustworthy. A confident verdict can safely drive a decision (such as letting the learner skip a follow-up test); an uncertain verdict tells AML to look more closely rather than guess.

## 3. How a single session works

Every time a learner answers a question, the engine runs the same short loop: it learns from the answer, updates what it believes about the learner’s understanding of that skill and related skills, checks whether it now knows enough about the learner, and if not, picks the single most useful next question. It stops when it is confident across the board about what the learner knows, or reaches the question limit for that grade.

![How a diagnostic session works](img/session_loop.png)

The key idea is “most useful next question.” The engine does not march through a fixed list. At each step it asks the one question that will teach it the most about this learner, then re-plans. This is why it can reach a confident picture of a learner with fewer questions than a fixed test.

## 4. What each learner is assessed on

The diagnostic covers four operations: addition, subtraction, multiplication, and division. Scope grows with grade, and it is **cumulative**: a Grade 5 learner is assessed on everything from the earlier grades plus Grade 5, not only Grade 5 content.

![What each learner is assessed on](img/scope_grid.png)

Each grade has a question limit (called a budget): 25 questions at Grade 2, 42 at Grade 3, 59 at Grade 4, and 76 at Grade 5. The diagnostic never exceeds the limit for a learner’s grade.

The diagnostic covers these four operations only. Place-value mistakes can still be spotted from a learner’s answers to the four operations above, in questions involving 2-digit or larger numbers (for example, an answer that shows the learner lined up the tens and units wrongly).

## 5. Online and offline: one engine, two ways to run it

AML's learners are often in places with patchy internet, so the diagnostic has to work whether or not there is a connection during the test. The same engine runs in two modes, and - this is the important part - a single learner's test can move between them without breaking.

![One engine, two modes](img/online_vs_offline.png)

- **Online** (good connection): a server picks each next question live and adapts fully to every answer.

- **Offline** (poor or no connection during the test): the device follows a pre-built "question map" that was prepared in advance using the very same engine logic, so no live connection is needed while the learner is answering.

Both modes produce the same kind of result: a confidence verdict for each of the learner's skills.

**One test, not two.** A learner does not pick "the online test" or "the offline test" at the start. They take one diagnostic, and it uses whichever mode fits the moment. Good connection: it runs online. Connection drops: the device carries on offline from exactly where the session was. Connection returns: it can hand control back to the server. A session can cross this line as many times as the connection wobbles, and it is always treated as one continuous test with one set of results.

![Mixed-mode: one session across online and offline](img/mixed_mode_handoff.png)

**A worked example: a child with intermittent internet.** Aisha is a Grade 3 learner in a classroom where the connection comes and goes. When she starts the diagnostic, her device has a brief moment of connectivity, and in that moment it downloads two things: the Grade 3 question map, and the questions that map could ask her. A few questions in, the connection drops. Her device does not stall: it keeps following the pre-built map, choosing each next question from her answers so far, and records each answer on the device. If the connection returns mid-test, the device can sync what it has and let the server take over again; if it stays down, the device simply finishes the test offline. Either way, when connectivity next returns (or overnight, when the app syncs), her recorded answers are sent to the server, which replays them through the engine and produces exactly the verdicts an online session would have produced on the same answers. Aisha never saw a spinner, and the result is the same.

**How the offline "question map" works, in plain terms.** The map is a decision tree prepared in advance, one per operation for the learner's grade. Picture a flowchart of questions: each question has two branches, one for a correct answer and one for a wrong one, and following those branches leads to the next question to ask. Because every path was worked out ahead of time using the same engine logic, the device only has to *follow* the map ("if right, go here; if wrong, go there"); it never has to do the engine's mathematics. The device works through the operations in a fixed order and in a few passes - first the core skills for the grade, then a little extra to catch common mistakes, then filling in any skills it is still unsure about - always stopping at the grade's question limit. The result is a full set of answers, ready to be scored the moment there is a connection.

**Who does what.** It helps to be clear about which part of the system has which job, because the device deliberately does *not* do the scoring:

| Job | Who does it |
|---|---|
| Show a question and read the learner's answer | the app on the device (online and offline) |
| While online: choose the next question | the engine, on the server |
| While offline: choose the next question by following the map | the app on the device |
| Mark each answer right or wrong | the app on the device |
| Record every answer, and sync it when there is a connection | the app on the device |
| Work out the mastery verdicts from the answers | the **engine**, on the server, when the answers arrive |
| Produce the final learning picture (verdict plus any misconception tag) | the data team, downstream |

The device's job is to run the test and record answers; the judgement - what the learner has and has not mastered - is always made on the server from the recorded answers, never on the device. This is why an offline test and an online test on the same answers reach the same verdicts.

**When a question has to be pulled at short notice.** Occasionally a question is taken off the app - a broken image, or a content fix - faster than the engine's own data can be updated. The system handles this without ever changing how answers are scored: the app can tell the engine which questions are switched off so it never offers them, can ask for a different question when one cannot be shown, and, offline, simply skips a question the device cannot display and moves on. All of these change *which* questions a learner sees, never *how* their answers are judged. The engineering and implementation specifications give the mechanics.

The offline mode is a little more cautious by design (it leaves more of a learner's skills marked "uncertain") because, without a live connection, it cannot use information across operations as flexibly. That caution is also why it makes fewer false skips. Section 12 covers this trade-off. Note that the offline mode still needs that one connected moment at the start to fetch the map and the questions; a learner who is offline from the very beginning (a "cold start") is out of scope for now.

## 6. What goes in, and what comes out

![What goes in and what comes out](img/inputs_outputs.png)

**Going in,** the engine uses three prepared ingredients:

- **Starting estimates:** how common mastery of each skill is in the population, so the engine has a sensible starting point about a learner before their first answer.

- **Skill relationships:** a small, curated map of which skills imply others (explained in Section 8).

- **A calibrated question bank:** the available questions, each with a known “quality” so the engine can prefer the sharper ones.

**Coming out,** for each of the learner’s skills, the engine gives one of three verdicts (confident mastered, uncertain, or confident not mastered) and a recommendation (skip the full MainD test for that skill, or take it).

A simplified example of what the engine returns for one learner:

{
  "learner_grade": 3,
  "skills": [
    { "skill": "2-digit Addition with carry",        "verdict": "confident_mastered",     "recommendation": "skip_maind" },
    { "skill": "3-digit Subtraction with borrowing",  "verdict": "uncertain",              "recommendation": "take_maind" },
    { "skill": "Tables 1, 2 and 5 (multiplication)",   "verdict": "confident_not_mastered", "recommendation": "take_maind" }
  ]
}

Here the learner can skip the MainD for 2-digit addition with carry (the engine is confident she has it), while the other two go to the full MainD - one because the engine is confident she has not mastered it, the other because the engine is not yet sure. (The full technical output, including the misconception tags of Section 10, is shown in the engineering specification.)

## 7. The three-band verdict

The engine tracks, for each of a learner’s skills, its confidence that the learner has mastered it, as a number between 0 and 1. It commits to “confident” only near the ends of that range, and stays “uncertain” in the wide middle.

![The three verdict bands and what each triggers](img/three_band.png)

- **Confident: mastered** leads to skipping the full MainD test for that skill, saving the learner time.

- **Uncertain** and **confident: not mastered** both lead to taking the full MainD, which then guides practice. The two are kept separate because the difference still matters for analysis and future tuning.

Keeping a clear “uncertain” band is deliberate. It is better for the engine to admit it is unsure about a learner and check than to make a confident-sounding guess that is wrong. The measured evidence backs this up: when the engine says “mastered” it is right 97 to 98% of the time, and when it says “not mastered” it is right about 88 to 92% of the time, while genuinely ambiguous cases land in “uncertain” rather than being forced into a wrong call (Section 9).

## 8. How the engine learns more from each answer: skill relationships

A learner who can do a harder skill can almost always do the easier skills underneath it. The engine uses a small, content-team-validated map of these relationships, so a single answer can teach it about several of the learner’s skills at once.

![How one answer informs related skills](img/lattice_example.png)

**A worked example.** One relationship in the map is: mastering **2-digit addition with carry** (call it Skill A) implies mastering **single-digit addition, 1-digit + 1-digit sums up to 20** (Skill B). In the Delhi data, a learner who has mastered A has about a 94% chance of having also mastered B. So when a learner answers the harder Skill A questions correctly, the engine can infer with high confidence that the learner also knows Skill B, and it does not need to spend any of the question budget testing B directly. The relationship also runs the other way: a wrong answer on a foundational skill lowers the engine’s confidence in the skills that build on top of it.

This is a large part of why the diagnostic is efficient: it does not need to test every skill directly, because one well-chosen answer updates the engine’s picture of several related skills.

## 9. What it improves over today’s static diagnostic

Measured against learners’ actual mastery records (with question responses simulated), using the current engine (v10), the dynamic diagnostic improves on the static one in four ways that matter. The full method and per-grade tables are in the comparison report.

![Skills each diagnostic can assess reliably](img/coverage_comparison.png)

![Dynamic vs static: accuracy and false skips](img/performance_comparison.png)

- **Confident verdicts on far more individual skills.** The static diagnostic has more than one question for only about 47% of individual (L2.5) skills, so at that fine level it can reliably judge only about half of them - which is why it reports at a coarser grade-and-broad-skill level rather than skill by skill. The dynamic engine gives a confident, skill-by-skill verdict on far more of a learner’s skills - about 92% online and about 80% offline - and routes the rest to MainD rather than guessing.

- **More accurate on the skills it commits to.** When the engine commits to a confident verdict, it is right 93% of the time online and 96% offline, against 87% for the static diagnostic. Counting every skill like-for-like (with “uncertain” treated as “take MainD”), the edge is smaller - about 89% online and 87% offline, versus 87% static - but the engine’s real strength is knowing when it does not know, and abstaining on the hard cases instead of committing to a wrong answer.

- **At least as safe overall, with one grade to watch.** A “false skip” is when the diagnostic says a learner has mastered a skill but they have not, so the learner wrongly skips practice. Across all skills the dynamic diagnostic makes no more false skips than the static one, and fewer offline (3.4% online and 2.1% offline, against 3.8% static). The exception is Grade 2, where both modes are slightly higher than the static test (2.3% online and 1.7% offline, against 1.4% static). The gap is small in absolute terms, but because it affects the youngest learners it is a deliberate watch-item, not something to average away (Section 12).

- **Less follow-up testing.** For each skill the engine confidently finds a learner has mastered, the learner skips that skill’s MainD questions. That is about 26 to 27 fewer follow-up questions per learner, 96 to 98% of those skips correct.

The dynamic diagnostic does **not** mainly save questions during the diagnostic itself. Those direct savings are modest (around 8% on average online, and close to zero offline, because the offline mode deliberately uses its question budget for thorough coverage). Counting the diagnostic and the follow-up MainD together, a learner answers on the order of 30 fewer questions overall than under the static approach, almost all of that from the MainD savings above. The real gains are accuracy, safety, and that combined reduction in testing.

## 10. Misconceptions

Beyond “mastered or not,” many wrong answers follow recognisable patterns, for example ignoring a carried digit, or confusing borrowing with carrying. A separate AML workstream, the **misconception classifier**, identifies these specific patterns. It uses a fixed catalogue of 139 codes across the four operations (Addition A01-A26, Subtraction S01-S31, Multiplication M01-M46, Division D01-D36); the full catalogue and the rule behind each code are listed in the engineering specification’s appendix.

It helps to be precise about who does what here, because two different components are involved:

- The **engine** makes sure the diagnostic *asks* questions that can reveal a learner’s misconceptions (it tracks which applicable misconceptions have been probed and, where the budget allows, prefers a question that probes one not yet seen). The engine’s mastery scoring uses only whether each answer was right or wrong, never the typed answer itself.

- A **separate classification step** reads the learner’s actual answers after the session (captured during the session and handed to this step) and works out which misconception, if any, each wrong answer matches. Its tag is then attached to that skill’s mastery verdict, so downstream practice can target the specific mistake.

This classification is built and has been verified in testing; it is not yet running in production, because nothing in this system is live yet. The pilot is the point at which the misconception signal can begin steering targeted practice.

**A worked example.** A learner is asked **45 + 27** and answers **62**. The classifier records:

- skill: 2-digit addition with carry,

- mastery verdict: not mastered,

- misconception: **A16** (the carried digit was ignored: 5 + 7 makes 12, but the carried ten was never added into the tens column, giving 6 instead of 7 there).

That tag travels with the verdict, so the learner’s practice can focus on the carry step itself rather than on addition in general.

## 11. How it fits into the AML product

- **Integration is the next build step.** The live AML product runs the static diagnostic today. Putting the dynamic diagnostic into AML is a defined piece of engineering work, sequenced as the online engine first, then the offline mode; a separate implementation guide lays out the steps.

- **It fits the way AML already works.** The engine produces a ready-to-use question for the app to show, and the app already records answers in a way the engine can score. Connecting the two is a matter of wiring, not of rebuilding either side. The per-question right/wrong records the engine needs for its mastery scoring are already captured today, and the app already has the offline-first response pipeline the offline mode relies on. The one addition is for misconception tagging: the learner’s typed answer needs to be sent to the engine alongside the right/wrong result - a small, optional field the engine now accepts, with the app-side change to send it still to be made.

## 12. Roadmap: what improves next

The diagnostic is ready to integrate and pilot today. The points below are the planned improvements and the honest limits of the current measurement; each has a clear path forward, and none blocks the pilot.

- **From simulation to classroom.** All the numbers here come from replaying learners’ real mastery records with simulated question responses, which is a strong test but not a live trial. Because the responses were simulated, the pilot is also the first test against real answer patterns (fatigue, streaks, question-specific difficulty). The first deployment is planned as a monitored pilot, which both confirms the results in the field and generates the live data that sharpens the engine.

- **Replaces the entry test now; a main-diagnostic mode comes later.** In this version the dynamic diagnostic is given in place of the current static entry test. A later mode will let the same engine run as an ongoing main diagnostic; that mode will need to avoid re-asking questions a learner already saw at entry - planned, but out of scope here.

- **Grade 2, and two specific weak buckets, are the ones to watch.** Grade 2 is where the engine is weakest today: its false-skip rate there is slightly above the static test (Section 9), and two buckets in particular - Grade 2 Subtraction and Grade 4 Addition - are, for now, confident-but-wrong more often than the static test on those buckets (when the engine commits there, it is right about 74 to 75% of the time, below static’s ~82 to 87%). These are not the safe “abstain when unsure” cases; they are cases where the engine commits and is wrong, so they are explicit targets for question-bank and calibration work and are front-of-list watch-items for the pilot.

- **Offline coverage will rise with local data.** The offline mode is deliberately more cautious: it leaves about one in five of a learner’s skills “uncertain” (roughly three times the online rate) because it cannot use cross-operation information live. Those skills are not wrong; they simply pass to MainD. As local data arrives and the offline question maps are rebuilt, this share is expected to fall.

- **Calibration broadens beyond Delhi.** The starting estimates are from Delhi data today. As other regions’ data arrives (Telangana next), the estimates are refreshed and the offline maps regenerated, improving accuracy and coverage for those regions.

- **Older grades need their own tuning.** Grade 6 to Grade 8 learners currently use the Grade 5 skill set, question budget, and Delhi Grade 5 starting estimates, which were not measured specifically for older learners. Refining the scope and estimates for them is a planned step.

- **The follow-up saving is a floor, not a ceiling.** It is measured only on the skills where a learner had a reliable mastery record, so the true per-learner saving is likely larger than the figure quoted.

- **Operational safeguards for the pilot.** Two are worth naming. First, if a false skip is later detected for a learner (for example, if the Grade 2 Subtraction weakness surfaces live), there needs to be a way to re-surface that skill’s MainD for that learner after the fact; defining that path is part of the pilot’s monitoring plan. Second, the first pilot runs a single engine instance, which comfortably handles pilot-scale concurrency (up to a few hundred learners testing at once); a large simultaneous rollout across many classrooms would need the standard step of running several engine copies, a known and planned scaling task rather than a new design.

## Appendix: the engine in a little more detail (optional)

This section is for readers who want the mechanism behind Sections 3 and 7. It still avoids formulas; the engineering specification has those.

**What it is based on.** The engine uses well-established methods. For each of a learner’s skills it holds a probability that the learner has mastered it, and revises that probability with each answer using Bayes’ rule (a standard way to update a belief in light of new evidence). Two allowances keep this realistic: a “slip” (even a learner who knows the skill sometimes answers wrong) and a “guess” (even a learner who does not know it sometimes answers right). Those slip and guess values are measured where the data supports it and otherwise borrowed from the nearest calibrated question, by a statistical calibration - a **two-class DINA model** (a standard item-difficulty model from educational testing) fit by an **Expectation-Maximization** procedure that does not require knowing in advance who has mastered what. In this build about 55 of the 667 questions are measured directly and the rest are borrowed. In short: the runtime engine is a Bayesian mastery tracker; the question-difficulty numbers it relies on come from the DINA calibration. The two are different layers and use different methods.

**How a belief updates.** When the learner answers a question on a skill, the engine revises the probability that the learner has mastered it up (for a correct answer) or down (for a wrong one). The size of the revision depends on the question’s quality: a sharp, well-calibrated question moves the belief more than a weak one.

**How related skills move together.** When the engine’s belief about one skill changes, it nudges its beliefs about related skills along the relationship map (Section 8), by an amount set by how strongly one skill predicts another. This is how one answer can inform the engine’s picture of several of the learner’s skills.

**How the next question is chosen.** Among the skills it is still unsure about for this learner, the engine favours the one where an answer would remove the most uncertainty and, through the relationship map, also move the most related skills. It then picks a high-quality question for that skill, varying the exact question so the same items are not shown to everyone.

**When it stops.** A skill is settled once the engine’s confidence about the learner is high enough at either end. The session ends when every in-scope skill is settled or the grade’s question limit is reached; any still-unsettled skills are reported as “uncertain.”

**The misconception classifier (Section 10).** The classifier is a rules-based system, one module per operation, that reads a learner’s actual answer to a question and matches it against a catalogue of 139 known error patterns (Addition A01-A26, Subtraction S01-S31, Multiplication M01-M46, Division D01-D36). Each module works through its codes in a fixed order and returns the first that matches, with a catch-all code for unrecognised errors. It takes, per answered question, the skill, the operation, the two numbers, the learner’s raw answer, and (for division) whether a remainder was expected; it returns, per skill, the misconception code where one applies. The engine’s mastery scoring never uses the raw answer; this classification step runs separately - reading the raw answers the engine has stored for it - and its tag is merged onto the engine’s verdict afterwards. The full code list and the rule behind each code are in the engineering specification’s appendix.