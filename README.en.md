# Taiwan Alpha Governance

**繁體中文：[README.md](README.md)**

The **governance record** of a Taiwan-equity quantitative research project.

There is no profitable strategy here. What is here is the other thing: **a full set of machinery for not fooling yourself**, and the record of every time it caught the author doing exactly that.

---

## ⚠️ Read this first

- **This is not investment advice.** The author is not a licensed adviser, and this repository recommends no security, strategy or broker.
- **No strategy has been validated.** Candidates at `validated`: **0**. The sealed out-of-sample data has been **opened 0 times**.
- **No real money has ever been traded.** The NT$10,000 canary milestone is still `blocked`, and it is designed so that even unblocking it would validate the *process*, never the strategy — [the arithmetic is here](docs/m0-project-contract.md).
- **You cannot run the data pipeline.** It needs licensed vendor data and a second, unpublished repository. See [what runs](#what-runs-and-what-does-not).
- Past backtest results do not predict future returns. Here, "it worked in the past" has not even been established.

---

## What this project is

Validating one complete Taiwan-equity pipeline on NT$10,000: official raw data → point-in-time warehouse → trading rules and costs → cash/share ledger → candidate strategies → nested validation → shadow → paper → canary.

**The capital is small on purpose.** It is small enough that no cost assumption can hide: on an NT$904 position, one round trip of commission and tax is **4.67%**. Anything that still looks viable at that scale is probably not an illusion at another.

The pipeline has reached M7. The most substantive research finding so far is a negative one:

| Ranking function | Rank IC | t-stat | NDCG@10 |
|---|---:|---:|---:|
| `momentum-12-1` | −0.0080 | −0.56 | 0.3891 |
| `inverse-volatility-60` | +0.0723 | +3.18 | 0.2962 |

**12-1 momentum's ranking ability is indistinguishable from zero** in this window and universe. Low volatility ranks the *whole cross-section* better, but the strategy only ever touches the top ten — and the top ten is a different question. One report measured both, separately, on purpose: [rank quality 001](docs/evidence/rank-quality-001-2026-08-28.md).

---

## What you can take from this

The data pipeline is only useful for Taiwan. None of the following is about Taiwan; all of it is about any work that draws conclusions from data.

**The sealed hold-out is split physically, not by self-discipline.** The development dataset that [`split_sealed_dataset.py`](scripts/m7/split_sealed_dataset.py) produces **does not contain** the sealed rows at all. A dataset missing those rows cannot produce results for those rows — which is stronger than any promise not to look. [Contract](docs/contracts/nested-validation-contract.md)

**A trial ledger, and why it exists.** This project carefully counted something that was 0 (seal openings) while counting nothing at all of the thing that was actually accumulating: development-set trials. By the time anyone noticed, nine had run — four of them a slot sweep that a decision was then taken from, which is the textbook shape of multiple comparisons. **Nine unrecorded trials are worse than one recorded opening.** [Contract](docs/contracts/trial-ledger-contract.md)

**Measurement scale, separated from execution scale.** Return figures produced at NT$10,000 **may not** be used as evidence about a strategy: costs are 2.87% of turnover there against 0.38% at reference scale (7.6×), and slot rejections outnumber completed trades 3,607 to 1. That equity curve measures *which signals arrived first*, not which were best. The rule was adopted **before** the numbers were seen. [ADR-0002](docs/adr/0002-measurement-scale-separate-from-execution-scale.md)

**Thresholds are written down before the run.** Every candidate has a plan committed with a git timestamp, and every plan contains a **falsifiable expectation**. Once the expectation was confirmed but the stated reason for it was wrong — and that record turned out to be worth more than the pass. [Candidate 005](docs/evidence/m7-candidate-005-result-2026-08-29.md)

**A blocking condition must never rest on the contents of an unread document.** "Obtain document X, which states Y" was written twice; both times X existed and neither time did it state Y. The correct form is "obtain and read document X, and determine whether it states Y." [D19](docs/evidence/m3-owner-decision-d19-2026-08-29.md)

**Every result document has a "what this cannot support" section** — usually longer than the one above it.

---

## What runs, and what does not

| | After you clone |
|---|---|
| **1,061 tests** | **873 need nothing external and finish in 4 seconds.** The other 188 carry `needs_local_data`: they want the operator's warehouse and archives, and elsewhere they **skip with the reason printed** rather than pretending to pass. |
| **59 scripts** | **None of them run.** All point at the unpublished `tw-sepa-screener` repository and at licensed vendor data. |
| **129 documents** | All readable. **They are the substance of this repository.** |

```bash
python -m pytest -q -m "not needs_local_data"
```

That is also the lane the pre-commit hook runs. Drop the `-m` filter for everything; on a machine with the data that takes minutes, and the five slowest tests are 388s, 123s, 49s, 47s and 45s -- every one of them reading local data.

CI runs with `-ra` so every skip is listed by name. The point is to keep the boundary between "checked here" and "checked only on one machine" visible, rather than letting it quietly shrink.

---

## Current status

**There is exactly one source of status: the [milestone register](docs/milestone-register.md).**

This file used to carry a status table too. It fell behind the register twice — once for nine days, and once again directly below the paragraph explaining that it had fallen behind for nine days. **One status cannot have two spokesmen, so the table is gone.**

In short: M0–M6 `complete`, M7 `pending` (prerequisites cleared, seal unopened), M8/M9/M11 `pending`, M10/M12 `blocked`.

---

## Finding your way around

**[The full index is docs/INDEX.md](docs/INDEX.md)** (129 documents). Start with three:

1. [M0 project contract](docs/m0-project-contract.md) — market, capital, risk, prohibitions. Everything else presupposes it.
2. [Milestone register](docs/milestone-register.md) — where the work is and what it is stuck on.
3. [ADR-0001](docs/adr/0001-separate-taiwan-core-and-alphamaster-research.md) — why the research engine is kept apart from the production system.

The filenames carry information. A contract or plan is dated **earlier** than the run it governs, and that ordering is the evidence that the rules were not written after seeing the results.

Documents are in Traditional Chinese; code, comments and docstrings are in English.

---

## Architecture

```text
TWSE / TPEx / MOPS
        |
        v
tw-sepa-screener   official and point-in-time core (unpublished)
        |
        | versioned research dataset (read-only)
        v
AlphaMaster   research laboratory (external, AGPL-3.0)
        |
        | research-only candidate package
        v
Taiwan validation and cash-ledger replay
        |
        v
shadow -> paper -> human-approved canary -> formal
```

The research engine may not write to formal strategies, the paper ledger or live orders; AI analysis may not enter any automatic scoring, promotion or order path. [ADR-0001](docs/adr/0001-separate-taiwan-core-and-alphamaster-research.md)

---

## What this repository does **not** contain

- **Licensed vendor data.** TEJ exports have never entered version control, and three independent guards keep it that way: `.gitignore`, a pre-commit hook, and CI.
- **The broker's own documents.** The terms, their hash and their provenance are [recorded here](docs/evidence/broker-terms-provenance-2026-08-29.md); the source document is not published, because together with the account-opening date it forms a personal financial profile. That same document states plainly **how much evidentiary strength was lost** by withholding it.
- **AlphaMaster's code.** It is an external AGPL-3.0 repository. Nothing from it is vendored here, and an invariant test enforces that.
- **Any real account data.** No account numbers, no orders, no fills.

---

## Issues and pull requests

**Issues are welcome**, especially methodological ones: a threshold that is badly designed, a step of reasoning that does not follow, a control group that is missing. Being wrong in public is the point, and this project has about exhausted its ability to catch itself.

**Most pull requests will not be merged, for structural reasons**:

- Everything under `docs/` is a **signed record**, not a collaboratively edited wiki. Decisions are made by a single Product Owner and carry a version; an external edit would make "who decided what, and when" meaningless.
- `m4/rules.py` and `m5/ledger.py` are byte-identical mirrors of another repository. Changing only this side is rejected by `test_upstream_parity.py`. Open an issue instead; the fix has to land upstream.
- Typos, dead links, and bugs in the tests themselves: send a PR, it will be merged.

---

## Licence

[Apache License 2.0](LICENSE).

The parts most likely to be useful elsewhere are `m4/rules.py` (Taiwan tick sizes, all three price-limit regimes, T+2, odd lots) and `m5/ledger.py` (the cash and share ledger). The tick table was derived empirically from 406,445 official closing prices, and every price-limit case is verified against officially published values. Both files are byte-identical mirrors of another repository, and [one test](tests/invariant/test_upstream_parity.py) makes sure they never diverge.
