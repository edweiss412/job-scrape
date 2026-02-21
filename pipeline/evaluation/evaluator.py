"""LLM evaluation engine: ResumeEvaluator class."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from pipeline.config import console, log, SCRIPT_DIR, resolve_model
from pipeline.models import JobListing
from pipeline.urls import _is_indirect_url, _resolve_apply_url
from pipeline.scrapers import fetch_job_description


# ---------------------------------------------------------------------------
# Supabase headers helper (inlined to avoid circular imports with sync/)
# ---------------------------------------------------------------------------
def _supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# LLM Evaluation (Claude)
# ---------------------------------------------------------------------------
class ResumeEvaluator:
    """
    Uses an LLM to score each job listing against the resume.
    Supports OpenRouter, Anthropic (direct), and any OpenAI-compatible endpoint.
    Returns a 0-100 match score and reasoning.
    """

    def __init__(self, config: dict, resume_text: str, role: str = "job_eval", user_id: str | None = None):
        self.resume_text = resume_text
        self._role = role
        self.user_id = user_id  # for cost attribution in multi-user evals
        self.candidate_context = config.get("candidate_context", "")
        self.city_profiles = config.get("city_profiles", {})
        self.home_city = config.get("home_city", "Chicago, IL")
        self.current_income = int(config.get("current_income", 85000))
        home_profile = self.city_profiles.get(self.home_city, {})
        self.home_neighborhood = home_profile.get("neighborhood", self.home_city)
        self.client = None
        self.new_job_ids = set()  # job_ids evaluated fresh this run (not cached)
        self.cache_path = SCRIPT_DIR / "eval_cache.json"  # override per-user via evaluator.cache_path
        self._last_usage = None  # token usage from most recent _call_llm

        self.provider, self.model = resolve_model(config, role)

        if self.provider == "openrouter":
            api_key = config.get("openrouter_key", "")
            if not api_key:
                log.warning("OpenRouter key not set")
                return
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
            except ImportError:
                log.error("Install openai: pip install openai")

        elif self.provider == "anthropic":
            api_key = config.get("anthropic_key", "")
            if not api_key:
                log.warning("Anthropic key not set")
                return
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                log.error("Install anthropic: pip install anthropic")

        elif self.provider == "google_aistudio":
            api_key = config.get("google_aistudio_key", "")
            if not api_key:
                log.warning("Google AI Studio key not set")
                return
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except ImportError:
                log.error("Install google-genai: pip install google-genai")

        elif self.provider == "openai_compatible":
            base_url = config.get("openai_compatible_base_url", "http://localhost:1234/v1")
            api_key = config.get("openai_compatible_key", "not-needed")
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=base_url, api_key=api_key)
            except ImportError:
                log.error("Install openai: pip install openai")

        else:
            log.error(f"Unknown LLM provider: {self.provider}")

    def _call_llm(self, prompt: str, operation: str = None) -> str:
        """Send a prompt to the configured LLM and return the response text."""
        import time as _time
        from pipeline_utils import log_api_usage
        self._last_usage = None
        _start = _time.time()
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            self._last_usage = {
                "prompt_tokens": getattr(response.usage, "input_tokens", 0),
                "completion_tokens": getattr(response.usage, "output_tokens", 0),
            }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            log_api_usage(
                source="pipeline", category="llm", pipeline="job_scraper", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=self._last_usage["prompt_tokens"],
                completion_tokens=self._last_usage["completion_tokens"],
                total_tokens=self._last_usage["prompt_tokens"] + self._last_usage["completion_tokens"],
                latency_ms=_latency, success=True, user_id=self.user_id,
            )
            return response.content[0].text.strip()
        elif self.provider == "google_aistudio":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "max_output_tokens": 4000,
                    "temperature": 0.5,
                },
            )
            um = getattr(response, "usage_metadata", None)
            if um:
                self._last_usage = {
                    "prompt_tokens": getattr(um, "prompt_token_count", 0),
                    "completion_tokens": getattr(um, "candidates_token_count", 0),
                }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            _pt = (self._last_usage or {}).get("prompt_tokens", 0)
            _ct = (self._last_usage or {}).get("completion_tokens", 0)
            log_api_usage(
                source="pipeline", category="llm", pipeline="job_scraper", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True, user_id=self.user_id,
            )
            return response.text.strip()
        else:
            # OpenRouter and OpenAI-compatible both use the OpenAI SDK
            extra_headers = {}
            if self.provider == "openrouter":
                extra_headers = {
                    "HTTP-Referer": "https://github.com/job-scraper",
                    "X-Title": "Job Search Pipeline",
                }
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
                extra_headers=extra_headers,
            )
            if response.usage:
                self._last_usage = {
                    "prompt_tokens": response.usage.prompt_tokens or 0,
                    "completion_tokens": response.usage.completion_tokens or 0,
                    "cost": getattr(response.usage, "cost", None),  # OpenRouter actual cost
                }
            _latency = int((_time.time() - _start) * 1000)
            _op = operation or self._role
            _pt = (self._last_usage or {}).get("prompt_tokens", 0)
            _ct = (self._last_usage or {}).get("completion_tokens", 0)
            _cost = (self._last_usage or {}).get("cost")
            log_api_usage(
                source="pipeline", category="llm", pipeline="job_scraper", operation=_op,
                provider=self.provider, model=self.model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                cost_usd=_cost, latency_ms=_latency, success=True, user_id=self.user_id,
            )
            return response.choices[0].message.content.strip()

    def _city_profiles_str(self) -> str:
        """Format city relocation profiles for injection into the prompt."""
        if not self.city_profiles:
            return ""
        baseline = self.city_profiles.get(self.home_city, {})
        baseline_rent = baseline.get("rent_1br", 0)
        baseline_tax = baseline.get("tax_rate", 0)
        baseline_cost = baseline.get("monthly_cost", 0)

        lines = [
            f"RELOCATION REFERENCE DATA (candidate baseline: {self.home_neighborhood} — "
            f"${baseline_rent:,}/mo rent, {baseline_tax:.1%} tax, ${baseline_cost:,}/mo total):\n"
        ]
        for city, profile in self.city_profiles.items():
            if city == self.home_city:
                continue
            premium = profile.get("annual_premium", 0)
            premium_str = f"+${premium:,}/yr" if premium > 0 else f"-${abs(premium):,}/yr (cheaper)"
            lines.append(
                f"  {city} ({profile.get('neighborhood', '?')}):\n"
                f"    Rent: ${profile.get('rent_1br', '?'):,}/mo | Tax: {profile.get('tax_rate', 0):.1%} "
                f"| Total: ${profile.get('monthly_cost', '?'):,}/mo ({premium_str} vs {self.home_city})\n"
                f"    Commute: {profile.get('commute', '?')}\n"
                f"    Walk: {profile.get('walk_score', '?')} | Bike: {profile.get('bike_score', '?')} "
                f"| Car required: {'Yes' if profile.get('car_required') else 'No'}\n"
                f"    Waterfront: {profile.get('waterfront', '?')}\n"
                f"    Notes: {profile.get('lifestyle_notes', '')}"
            )
        return "\n".join(lines)

    def _relocation_prompt_block(self, *, deep: bool = False) -> str:
        """
        Return the compensation & relocation analysis block for the prompt.
        Returns an empty string if home_city, current_income, or city_profiles
        are not set — so the section is silently omitted rather than broken.
        """
        if not self.home_city or not self.current_income or not self.city_profiles:
            return ""
        city_data = self._city_profiles_str()
        if not city_data:
            return ""
        income_k = self.current_income // 1000
        if deep:
            return (
                f"#### COMPENSATION & RELOCATION ANALYSIS\n"
                f"The candidate currently earns ~${income_k}K/year based in {self.home_neighborhood}. "
                f"Use the relocation reference data below to perform a full financial and lifestyle "
                f"comparison for any role outside {self.home_city}. Show your math.\n"
                f"{city_data}"
            )
        return (
            f"- COMPENSATION & RELOCATION ANALYSIS: The candidate currently earns ~${income_k}K/year "
            f"based in {self.home_neighborhood}. Use the relocation reference data below to perform a "
            f"full financial and lifestyle comparison for any role outside {self.home_city}. "
            f"For each non-{self.home_city} role:\n"
            f"  1. Estimate or use the listed salary\n"
            f"  2. Calculate the annual relocation premium from the reference data (rent + tax difference)\n"
            f"  3. Add car ownership costs ($6,000-9,600/yr) if car_required=Yes for that city\n"
            f"  4. Calculate **net annual gain** = (new salary - ${income_k}K) - annual_premium - car_costs\n"
            f"  5. If net annual gain is negative or negligible (<$5K), downgrade the match by one level\n"
            f"  6. Factor in lifestyle: Walk Score, Bike Score, waterfront access, commute. "
            f"If a move represents a significant QOL downgrade from {self.home_neighborhood}, note it clearly\n"
            f"  7. A permanent role also offers benefits (health insurance, 401k match, PTO) "
            f"worth ~$15-25K/yr — factor this into the comparison vs. current income\n"
            f"  Always show your math in the RED FLAGS and LOGISTICS sections.\n"
            f"{city_data}\n"
            f"- LOCATION MATTERS: Use the candidate's context above to determine their relocation "
            f"preferences. Suburban or car-dependent locations should be flagged as a negative if "
            f"the candidate prefers walkable urban areas."
        )

    def evaluate(self, job: JobListing) -> dict:
        """
        Score a job against the resume using the full structured evaluation.
        Returns dict with score, verdict, reasoning (short), and full_evaluation.
        """
        # Lazy import to avoid circular dependency at module load time.
        # These constants are only needed at call time.
        from pipeline.evaluation.prefilter import RELEVANT_TITLE_KEYWORDS, TARGET_COMPANY_KEYWORDS

        if not self.client or not self.resume_text:
            return {
                "score": 0, "verdict": "", "reasoning": "Evaluation skipped",
                "full_evaluation": "",
            }

        description_missing = not job.description or len(job.description.strip()) < 50

        if description_missing:
            desc_text = (
                "(No description available. You MUST NOT fabricate or assume job requirements. "
                "Evaluate ONLY what can be confirmed from the title and company name. "
                "Cap your verdict at MODERATE maximum — without a description, a STRONG rating is not justified.)"
            )
        else:
            desc_text = job.description

        job_info = f"""Title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}
Salary: {job.salary or 'Not provided in structured data — look for pay/salary/rate/compensation in the description below'}
Company Tier: {job.tier or 'N/A'}

Description:
{desc_text}"""

        prompt = f"""You are a senior technical recruiter specializing in the full spectrum of AV and live events disciplines — including audio/sound, lighting, video/LED, projection, show control, staging/rigging, broadcast, and corporate AV. You have deep knowledge of both the freelance production world and the permanent in-house corporate world. Your job is to evaluate a job posting against the candidate's resume.

CANDIDATE RESUME:
{self.resume_text}

ADDITIONAL CONTEXT ABOUT THE CANDIDATE:
{self.candidate_context}

JOB POSTING:
{job_info}

---

Perform the following evaluation:

### 1. ROLE SUMMARY
- Company name, actual role (translate past any disguised titles — e.g., "Technology Delivery, VP" = Lead Audio Engineer), location, and compensation (extract from the job description even if the Salary field above says "Not provided" — look for dollar amounts, hourly rates, salary ranges, or pay bands anywhere in the posting text)
- Is this an in-house permanent role, a contract, or a staffed/embedded integrator position?
- On-site requirements (hybrid, fully on-site, remote) and any relocation implications
- Industry vertical (financial services, pharma, tech, education, entertainment, etc.)

### 2. MATCH SCORE
Score each dimension 1–5 honestly. 3 = adequate, NOT a safe default. Show scores in a table:

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Core Skills | _/5 | 5=meets nearly all required skills, 3=meets ~half, 1=almost no overlap. Weight REQUIRED qualifications heavily; "preferred" / "nice to have" / "strong candidates may also have" sections are bonuses, not gaps. Different AV sub-disciplines count as partial gaps even if both are "AV" — e.g. lighting vs audio, integration vs live production, post-production vs live events, video engineering vs show control. Score 2 unless there is genuine day-to-day skill overlap (shared gear, shared workflows, or transferable console/protocol experience) |
| Seniority Fit | _/5 | 5=perfect level, 3=slightly off, 1=wildly mismatched (too junior or senior) |
| Compensation | _/5 | 5=clear upgrade, 3=lateral, 1=major pay cut. Check the description for pay info even if the Salary field says "Not provided." Only default to 3 if no compensation is mentioned anywhere in the posting |
| Logistics | _/5 | 5=ideal location/setup, 3=workable with trade-offs, 1=dealbreaker |
| Career Value | _/5 | 5=clearly advances goals, 3=neutral, 1=step backward or dead end |

**WEIGHTED COMPOSITE** = (2\u00d7Core Skills + Seniority + Compensation + Logistics + Career Value) / 6
\u2191 Core Skills counts DOUBLE \u2014 a job you can't do is a bad match regardless of pay.
Calculate explicitly, e.g. "(2\u00d74 + 3 + 2 + 4 + 3)/6 = 2.67"

Use the FULL 1\u20135 range. 5 means excellent (not perfect). 1 means dealbreaker or clearly wrong. Don't compress everything into 2\u20134.

Map weighted composite to verdict:
- **3.8\u20135.0** \u2192 \U0001f7e2 STRONG \u2014 Apply with confidence. Core skills align and circumstances work.
- **2.6\u20133.7** \u2192 \U0001f7e1 MODERATE \u2014 Worth applying, but meaningful concerns to address.
- **1.6\u20132.5** \u2192 \U0001f7e0 STRETCH \u2014 Major gaps or practical barriers. Only if strategically motivated.
- **1.0\u20131.5** \u2192 \U0001f534 WEAK \u2014 Wrong role, wrong level, or impractical. Skip it.

**Override rules** (apply AFTER computing composite \u2014 these are hard caps):
- If Core Skills \u2264 2 \u2192 verdict CANNOT exceed STRETCH, regardless of composite. A job in the wrong discipline is not a good match no matter how well it pays.
- If Seniority Fit = 1 \u2192 verdict CANNOT exceed STRETCH. A wildly mismatched level (entry-level for a 15-year veteran, or VP for a mid-career professional) is not worth pursuing.

**Calibration anchors** \u2014 use these to gut-check your scoring. The candidate's discipline determines which anchors apply; match the resume to the right row:

*Same-discipline matches (candidate's skills align with the posting):*
- Corporate AV role, Crestron/Extron/Dante, good pay, candidate's own city \u2192 (2\u00d75+4+4+5+4)/6 = **4.5 STRONG**
- Lighting designer role, ETC Eos/grandMA, touring or venue, good pay, candidate's city \u2192 (2\u00d75+4+4+5+4)/6 = **4.5 STRONG**
- Video engineer role, Disguise/Resolume/LED processing, live events, good pay \u2192 (2\u00d75+4+4+5+4)/6 = **4.5 STRONG**
- Show control programmer, QLab/Medialon/Watchout, theme park or touring \u2192 (2\u00d75+4+4+4+4)/6 = **4.3 STRONG**
- Same-discipline role but requires relocation for a pay upgrade \u2192 (2\u00d75+4+4+3+4)/6 = **4.2 STRONG**
- Same-discipline role but lateral pay AND costly relocation \u2192 (2\u00d75+4+2+2+4)/6 = **3.7 MODERATE**

*Cross-discipline or partial matches:*
- Lighting role for an audio engineer (different consoles, different workflow) \u2192 (2\u00d72+3+3+3+2)/6 = **2.5 STRETCH** + Core Skills \u2264 2 cap
- Broadcast post-production (Pro Tools HDX, Dolby Atmos) for a live-events person \u2192 (2\u00d72+3+4+3+2)/6 = **2.7 MODERATE** but Core Skills \u2264 2 cap \u2192 **STRETCH**
- AV integrator service/support (Crestron/AMX ticketing) for a live-production A1 \u2192 (2\u00d72+3+3+3+2)/6 = **2.5 STRETCH** \u2014 integration support \u2260 live production
- Video engineer role for a stagehand (some overlap in venue knowledge, not in daily skills) \u2192 (2\u00d72+3+3+3+2)/6 = **2.5 STRETCH** + Core Skills \u2264 2 cap

*Seniority / compensation mismatches:*
- Part-time venue gig, right skills but $20/hr and too junior \u2192 (2\u00d74+1+1+4+1)/6 = **2.5 STRETCH** (Seniority=1 cap also applies)
- Entry-level "AV Tech I" at $45K when candidate has 15+ yrs \u2192 (2\u00d73+1+1+3+1)/6 = **2.0 STRETCH** + Seniority=1 cap

*Wrong field entirely:*
- IT helpdesk / desktop support role with no AV \u2192 (2\u00d71+2+3+3+1)/6 = **1.8 STRETCH** + Core Skills \u2264 2 cap
- Warehouse associate or food service \u2192 (2\u00d71+1+1+3+1)/6 = **1.3 WEAK**

### 3. REQUIREMENTS ALREADY MET
List each requirement from the posting alongside the specific line, bullet, or section of the resume that demonstrates it. Be precise \u2014 cite actual resume content.

### 4. REQUIREMENTS WITH EXPERIENCE BUT NOT HIGHLIGHTED
Things the candidate can likely do based on the full picture of the resume and context but that aren't explicitly stated or are buried. For each, suggest where and how to surface it in a tailored version.

### 5. TRUE GAPS
Requirements where the candidate genuinely lacks the qualification or experience. Be honest \u2014 don't stretch. For each gap, note:
- How critical it appears to be (dealbreaker vs. nice-to-have vs. learnable)
- Whether it's something that could realistically be developed quickly or addressed in a cover letter

### 6. RED FLAGS
- Anything that seems off about the posting (vague requirements, unrealistic expectations, title/comp mismatch)
- Any requirements that suggest a different seniority level (too junior or too senior)
- ATS keywords from the posting that are missing from the resume

### 7. LOGISTICS
- Location/relocation requirements and whether they're feasible given {self.home_city} base
- Salary range (if listed) and whether it aligns with experience level
- On-site / hybrid / remote details and commute implications

### 8. VERDICT
Answer three questions directly:
1. **Should I apply?** Yes / Yes but temper expectations / Only if genuinely interested in this company / No
2. **Is it worth tailoring my resume?** Yes \u2014 significant tailoring needed / Light tailoring only / No \u2014 baseline resume is sufficient
3. **What's the single most important thing to change or add if tailoring?** One specific, actionable recommendation.

---

RULES:
- Be direct and honest. Say "this is a weak match, don't waste your time" if that's the case.
- Don't inflate qualifications. If the resume doesn't demonstrate something, say so.
- Pay attention to disguised titles. AV/live events roles are frequently hidden behind titles like "Technology Delivery," "Multimedia Specialist," "Event Technology Manager," "Collaboration Engineer," "Technical Specialist," "Production Coordinator," etc. Translate these to the actual discipline (audio, lighting, video, show control, staging, etc.).
- When a posting lists "required" vs. "preferred" qualifications, weigh them differently.
- If the posting is vague or poorly written, say so.
- VERDICT CALIBRATION: Do NOT default to MODERATE. Trust your dimensional scores and apply the override rules. If the composite is below 2.6 (or override rules apply), commit to STRETCH or WEAK. If it's 3.8+ with no overrides, commit to STRONG. A typical job search yields a MIX of all four verdicts.
{self._relocation_prompt_block()}

After the full evaluation, add final lines in exactly this format:
JOB_SUMMARY: [2-sentence plain-text summary of the role itself. Do NOT mention the candidate.]
COMPOSITE_SCORE: [your calculated average, e.g., 3.4]
MATCH_LEVEL: [STRONG|MODERATE|STRETCH|WEAK]

CRITICAL: The MATCH_LEVEL must follow directly from your COMPOSITE_SCORE using the thresholds above,
AFTER applying the override rules (Core Skills \u2264 2 \u2192 STRETCH max; Seniority Fit = 1 \u2192 STRETCH max).
Do not override your dimensional scoring with a gut feeling. Trust the math \u2014 that's the whole point
of scoring dimensions first. If overrides apply, state which one and adjust the verdict accordingly."""

        try:
            text = self._call_llm(prompt)

            # --- Parse dimension scores from the table and recompute composite ---
            # LLMs frequently make arithmetic errors; we recompute to be safe.
            dim_names = ["Core Skills", "Seniority Fit", "Compensation", "Logistics", "Career Value"]
            dim_scores = {}
            for dim in dim_names:
                # Match patterns like "| Core Skills | 4/5 |" or "| **Core Skills** | **4**/5 |"
                pat = re.compile(
                    rf"\|\s*\**{re.escape(dim)}\**\s*\|\s*\**(\d)\**\s*(?:/5)?\s*\|",
                    re.IGNORECASE,
                )
                m = pat.search(text)
                if m:
                    dim_scores[dim] = int(m.group(1))

            # Recompute weighted composite if we got all 5 dimensions
            recalc_composite = None
            if len(dim_scores) == 5:
                cs = dim_scores["Core Skills"]
                sf = dim_scores["Seniority Fit"]
                co = dim_scores["Compensation"]
                lo = dim_scores["Logistics"]
                cv = dim_scores["Career Value"]
                recalc_composite = round((2 * cs + sf + co + lo + cv) / 6, 2)

            # Extract COMPOSITE_SCORE from trailing tag (model's own calculation)
            comp_match = re.search(r"COMPOSITE_SCORE:\s*\**\s*([\d.]+)", text)
            model_composite = float(comp_match.group(1)) if comp_match else None

            # Use recalculated composite (authoritative); fall back to model's
            composite = recalc_composite if recalc_composite is not None else model_composite

            # --- Determine verdict from composite + override rules ---
            verdict = ""
            score = 0

            if composite is not None:
                # Apply threshold mapping
                if composite >= 3.8:
                    verdict = "STRONG"
                elif composite >= 2.6:
                    verdict = "MODERATE"
                elif composite >= 1.6:
                    verdict = "STRETCH"
                else:
                    verdict = "WEAK"

                # Apply override rules (hard caps from the prompt)
                if dim_scores:
                    if dim_scores.get("Core Skills", 5) <= 2 and verdict in ("STRONG", "MODERATE"):
                        verdict = "STRETCH"
                    if dim_scores.get("Seniority Fit", 5) == 1 and verdict in ("STRONG", "MODERATE"):
                        verdict = "STRETCH"

            else:
                # Fallback: extract MATCH_LEVEL tag from text
                level_match = re.search(
                    r"MATCH_LEVEL:\s*\**(?:\U0001f7e2|\U0001f7e1|\U0001f7e0|\U0001f534)?\s*\**\s*(STRONG|MODERATE|STRETCH|WEAK)",
                    text,
                )
                if not level_match:
                    level_match = re.search(
                        r"\*{0,2}MATCH_LEVEL\*{0,2}:\s*\**\s*(STRONG|MODERATE|STRETCH|WEAK)",
                        text,
                    )
                if level_match:
                    verdict = level_match.group(1)
                else:
                    # Last resort: detect from emoji
                    if "\U0001f7e2" in text:
                        verdict = "STRONG"
                    elif "\U0001f7e1" in text:
                        verdict = "MODERATE"
                    elif "\U0001f7e0" in text:
                        verdict = "STRETCH"
                    elif "\U0001f534" in text:
                        verdict = "WEAK"

            # Handle missing description: smart cap based on title/company signals
            description_confidence = "full"
            if description_missing:
                title_lower = job.title.lower()
                company_lower = job.company.lower()
                title_kw_hits = sum(1 for kw in RELEVANT_TITLE_KEYWORDS if kw in title_lower)
                company_match = any(kw in company_lower for kw in TARGET_COMPANY_KEYWORDS)

                if verdict == "STRONG" and (title_kw_hits >= 2 or company_match):
                    # Strong title/company signal — allow STRONG but flag reduced confidence
                    description_confidence = "title_only"
                    log.info(f"Allowing STRONG for {job.title} @ {job.company} (no desc, but {title_kw_hits} title kws, company_match={company_match})")
                elif verdict == "STRONG":
                    # Ambiguous title — cap at MODERATE
                    description_confidence = "limited"
                    log.warning(f"Capping {job.title} @ {job.company} from STRONG \u2192 MODERATE (no description, weak title signal)")
                    verdict = "MODERATE"
                else:
                    description_confidence = "limited"

            # Compute score: prefer composite for granularity, fall back to fixed mapping
            if composite is not None:
                score = max(1, min(100, int(composite * 20)))  # 1-5 -> 20-100
            else:
                score = {"STRONG": 85, "MODERATE": 70, "STRETCH": 50, "WEAK": 25}.get(verdict, 0)

            # Adjust score cap based on description confidence
            if description_missing and description_confidence == "limited" and score > 80:
                score = 80

            # Extract JOB_SUMMARY from trailing tags
            job_summary = ""
            summary_match = re.search(
                r"JOB_SUMMARY:\s*(.+?)(?:\n(?:COMPOSITE_SCORE|MATCH_LEVEL))", text, re.DOTALL,
            )
            if summary_match:
                job_summary = summary_match.group(1).strip()

            # Extract a short reasoning from the verdict section
            reasoning = ""
            verdict_section = re.search(
                r"###?\s*8\.?\s*VERDICT(.*?)(?:JOB_SUMMARY|COMPOSITE_SCORE|MATCH_LEVEL|$)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if verdict_section:
                reasoning = verdict_section.group(1).strip()[:500]

            # Clean the trailing JOB_SUMMARY, COMPOSITE_SCORE, and MATCH_LEVEL lines
            full_eval = re.sub(r"\n?JOB_SUMMARY:.*$", "", text, flags=re.DOTALL).strip()
            full_eval = re.sub(r"\n?COMPOSITE_SCORE:.*$", "", full_eval).strip()
            full_eval = re.sub(r"\n?MATCH_LEVEL:.*$", "", full_eval).strip()

            return {
                "score": score,
                "verdict": verdict,
                "reasoning": reasoning,
                "full_evaluation": full_eval,
                "job_summary": job_summary,
                "description_confidence": description_confidence,
            }

        except Exception as e:
            log.error(f"LLM evaluation error: {e}")
            return {
                "score": 0, "verdict": "", "reasoning": f"Evaluation failed: {e}",
                "full_evaluation": "", "job_summary": "",
            }

    def deep_evaluate(self, job: JobListing, config: dict, first_pass_eval: str = "") -> str:
        """
        Generate application prep package for a STRONG match job.
        Uses the first-pass evaluation as context (no redundant re-scoring)
        and produces 3 sections: Resume Tailoring, Cover Letter, Interview Prep.
        Returns a detailed markdown string.
        """
        # Skip deep eval when description is missing — can't generate useful prep
        if not job.description or len(job.description.strip()) < 50:
            log.warning(f"Skipping deep eval for {job.title} @ {job.company} — no description available")
            return ""

        deep_evaluator = ResumeEvaluator(config=config, resume_text=self.resume_text, role="deep_eval")
        if not deep_evaluator.client:
            log.error("Failed to initialize deep evaluation model")
            return ""

        job_info = f"""Title: {job.title}
Company: {job.company}
Location: {job.location}
Source: {job.source}
Salary: {job.salary or 'Not provided in structured data — check the description for pay/salary/rate info'}
Company Tier: {job.tier or 'N/A'}

Description:
{job.description or '(No description available — evaluate based on title/company only)'}"""

        # Build first-pass context block
        first_pass_block = ""
        if first_pass_eval:
            first_pass_block = f"""
FIRST-PASS EVALUATION (already completed — use this as context, do NOT repeat it):
{first_pass_eval}

---
"""

        prompt = f"""You are a senior technical recruiter with 15+ years of experience placing AV, broadcast, and live event engineers into permanent corporate roles. You've worked at firms like PRG, PSAV (now Encore), and Clair Global, and have deep relationships with hiring managers at major financial services firms and Fortune 500 pharma companies. You know exactly what makes a candidate stand out — and what gets a resume thrown in the "no" pile.

This job has already been evaluated as a STRONG match. A first-pass evaluation with match analysis, requirements mapping, gaps, and logistics is provided below. Your job is to produce the APPLICATION PREP PACKAGE — the actionable deliverables the candidate needs to actually apply and interview.

CANDIDATE RESUME:
{self.resume_text}

ADDITIONAL CONTEXT ABOUT THE CANDIDATE:
{self.candidate_context}

JOB POSTING:
{job_info}
{first_pass_block}
Produce the following 3-section application prep package. Be thorough, specific, and actionable. Write as if you're personally coaching this candidate before they apply.

### 1. RESUME TAILORING
This is where you earn your fee. For each suggestion:
- Quote the EXISTING bullet point or section from the resume (use "**BEFORE:**" formatting)
- Write the REWRITTEN version (use "**AFTER:**" formatting)
- Explain WHY the change matters for this specific posting
- If a bullet point should be ADDED (not rewritten), mark it as "**ADD:**" with the suggested placement

Focus on:
- ATS keyword optimization (pull exact phrases from the posting)
- Reframing freelance experience to emphasize the skills this employer cares about
- Quantifying impact where possible
- Moving the most relevant experience to prominent positions

Provide at least 5-7 specific before/after rewrites. More is better — the candidate should be able to make all changes in 30 minutes.

### 2. COVER LETTER TALKING POINTS
Write 3-5 key talking points for the cover letter, framed in terms of "what would make me pick up the phone and call this candidate." For each point:
- The core message (one sentence)
- Why it matters to THIS employer specifically
- A suggested opening line or phrase the candidate could use

Think like a recruiter scanning 200 applications — what makes this one jump off the page?

### 3. INTERVIEW PREP
Based on this posting, prepare the candidate for the interview:
- **Likely technical questions** (5-7 specific questions they'll probably ask, based on the role requirements)
- **Behavioral/situational questions** (3-5 questions about experience, especially around any gaps or transitions)
- **Questions about the freelance-to-permanent transition** — how to frame this positively
- **Stories to prepare** — specific projects or experiences from the resume that map to this role's key requirements. Name the project/client and the talking point.
- **Questions to ASK the interviewer** — 3-5 smart questions that show domain knowledge and genuine interest

---

RULES:
- Begin your response directly with ### 1. RESUME TAILORING — no preamble, no intro paragraph, no framing text.
- Be direct and brutally honest. This candidate can handle it.
- Don't inflate qualifications. If something is a gap, say so — then help them address it.
- Write as if you're personally preparing this candidate for a specific interview, not generating generic advice.
- Every suggestion should reference specific content from either the resume or the job posting.
- The resume tailoring section is the most important — make it specific enough that the candidate can make changes in 30 minutes.
- Use the first-pass evaluation as a foundation — don't contradict its analysis, but ADD actionable detail on top of it."""

        try:
            # Use higher token limit for deep evaluation
            if deep_evaluator.provider == "anthropic":
                response = deep_evaluator.client.messages.create(
                    model=deep_evaluator.model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()
            elif deep_evaluator.provider == "google_aistudio":
                response = deep_evaluator.client.models.generate_content(
                    model=deep_evaluator.model,
                    contents=prompt,
                    config={
                        "max_output_tokens": 8000,
                        "temperature": 0.5,
                    },
                )
                return response.text.strip()
            else:
                extra_headers = {}
                if deep_evaluator.provider == "openrouter":
                    extra_headers = {
                        "HTTP-Referer": "https://github.com/job-scraper",
                        "X-Title": "Job Search Pipeline",
                    }
                response = deep_evaluator.client.chat.completions.create(
                    model=deep_evaluator.model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                    extra_headers=extra_headers,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"Deep evaluation error for {job.title} @ {job.company}: {e}")
            return ""

    def _evaluate_single(self, job: JobListing, fetch_description: bool) -> dict:
        """Evaluate a single job (thread-safe). Returns (job, result) tuple."""
        # Resolve indirect URLs (Google search links, aggregators) to final destination
        if job.url and _is_indirect_url(job.url):
            job.url = _resolve_apply_url(job.url)
        # Only fetch description from web if not already stored (e.g. from Supabase)
        had_no_desc = not job.description
        if fetch_description and had_no_desc and job.url:
            job.description = fetch_job_description(job.url)
            # Write back to Supabase so other users and future runs benefit
            if job.description and len(job.description.strip()) >= 50:
                try:
                    supabase_url = os.environ.get("SUPABASE_URL", "")
                    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
                    if supabase_url and supabase_key:
                        requests.patch(
                            f"{supabase_url}/rest/v1/jobs?job_id=eq.{job.job_id}",
                            headers=_supabase_headers(supabase_key),
                            json={"description": job.description[:50000], "description_length": len(job.description)},
                            timeout=10,
                        )
                except Exception:
                    pass  # Best-effort; don't block eval
        if not job.description or len(job.description.strip()) < 50:
            log.warning(f"No description available for {job.title} @ {job.company} — evaluation will be capped")
        return self.evaluate(job)

    def _resume_hash(self) -> str:
        """Short hash of the current resume text for cache invalidation."""
        import hashlib
        return hashlib.md5(self.resume_text.encode()).hexdigest()[:12]

    def _load_eval_cache(self) -> dict:
        """Load eval cache - a persistent map of job_id -> evaluation results.
        Invalidates the entire cache if the resume has changed since it was written."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    data = json.load(f)
                stored_hash = data.get("_resume_hash", "")
                if stored_hash and stored_hash != self._resume_hash():
                    stale_count = len([k for k in data if not k.startswith("_")])
                    log.info(f"Resume changed — clearing {stale_count} stale cache entries ({self.cache_path.name})")
                    return {}
                return {k: v for k, v in data.items() if not k.startswith("_")}
            except (json.JSONDecodeError, Exception) as e:
                log.warning(f"Failed to load eval cache: {e}")
        return {}

    def _save_eval_cache(self, cache: dict):
        """Persist the eval cache to disk with a resume hash for invalidation."""
        data = {"_resume_hash": self._resume_hash()}
        data.update(cache)
        with open(self.cache_path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        log.info(f"Eval cache saved ({self.cache_path.name}): {len(cache)} entries")

    def evaluate_batch(
        self, jobs: list[JobListing], fetch_descriptions: bool = True,
        max_workers: int = 8, progress_callback=None, on_job_complete=None,
        cancel_check=None,
    ) -> list[JobListing]:
        """Evaluate a batch of jobs concurrently, skipping previously evaluated ones."""
        # Load cache of previous evaluations
        eval_cache = self._load_eval_cache()
        cached_jobs = []
        new_jobs = []
        for job in jobs:
            if job.job_id in eval_cache:
                cached = eval_cache[job.job_id]
                job.match_score = cached["score"]
                job.match_verdict = cached["verdict"]
                job.match_reasoning = cached["reasoning"]
                job.full_evaluation = cached["full_evaluation"]
                job.job_summary = cached.get("job_summary", "")
                cached_jobs.append(job)
            else:
                new_jobs.append(job)

        total_new = len(new_jobs)
        total_cached = len(cached_jobs)
        console.print(f"\n[bold]Evaluating {total_new} new jobs against resume...[/bold]")
        if total_cached:
            console.print(f"[dim]Skipping {total_cached} previously evaluated jobs (cached)[/dim]")
        console.print(f"[dim]Provider: {self.provider} | Model: {self.model} | Workers: {max_workers}[/dim]")

        verdict_style_map = {
            "STRONG": "green bold",
            "MODERATE": "yellow",
            "STRETCH": "rgb(255,165,0)",
            "WEAK": "dim",
        }

        completed = 0
        cancelled = False
        if new_jobs:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_job = {
                    executor.submit(self._evaluate_single, job, fetch_descriptions): (i, job)
                    for i, job in enumerate(new_jobs)
                }

                for future in as_completed(future_to_job):
                    # Check for cancellation every 3 completed jobs
                    if cancel_check and completed > 0 and completed % 3 == 0:
                        if cancel_check():
                            console.print("\n[bold red]Cancellation requested — stopping evaluation[/bold red]")
                            cancelled = True
                            # Cancel remaining futures
                            for f in future_to_job:
                                f.cancel()
                            break

                    i, job = future_to_job[future]
                    completed += 1
                    try:
                        result = future.result()
                        job.match_score = result["score"]
                        job.match_verdict = result["verdict"]
                        job.match_reasoning = result["reasoning"]
                        job.full_evaluation = result["full_evaluation"]
                        job.job_summary = result.get("job_summary", "")
                    except Exception as e:
                        log.error(f"Evaluation failed for {job.title}: {e}")
                        job.match_score = 0
                        job.match_verdict = ""
                        job.match_reasoning = f"Evaluation failed: {e}"
                        job.full_evaluation = ""

                    verdict_style = verdict_style_map.get(job.match_verdict, "white")
                    console.print(
                        f"  [{completed}/{total_new}] {job.title} @ {job.company}... "
                        f"[{verdict_style}]{job.match_verdict} ({job.match_score})[/{verdict_style}]"
                    )
                    if on_job_complete and job.match_verdict:
                        on_job_complete(job)
                    if progress_callback and completed % 5 == 0:
                        progress_callback(completed)

        # Track new job IDs and save into the cache (including partial results if cancelled)
        self.new_job_ids = {job.job_id for job in new_jobs if job.match_verdict}
        for job in new_jobs:
            if job.match_verdict:
                eval_cache[job.job_id] = {
                    "score": job.match_score,
                    "verdict": job.match_verdict,
                    "reasoning": job.match_reasoning[:300],
                    "full_evaluation": job.full_evaluation,
                    "job_summary": job.job_summary,
                }
        self._save_eval_cache(eval_cache)

        self._was_cancelled = cancelled
        return cached_jobs + new_jobs
