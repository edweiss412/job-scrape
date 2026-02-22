"""Pre-filter: keyword scoring, cheap LLM pass, and per-user role filtering."""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from pipeline.config import console, log, resolve_model
from pipeline.models import JobListing
from pipeline.sync.client import _supabase_headers


# ---------------------------------------------------------------------------
# Keyword constants for the pre-filter
# ---------------------------------------------------------------------------

RELEVANT_TITLE_KEYWORDS = {
    "audio", "av ", "a/v", "audiovisual", "audio visual", "audio-visual",
    "broadcast", "production engineer", "sound engineer", "sound technician",
    "av engineer", "av technician", "av specialist", "event technology",
    "conference services", "multimedia", "a1 ", "a2 ", "video engineer",
    # lighting
    "lighting designer", "lighting technician", "lighting director",
    "lighting programmer", "lighting engineer",
    # video / LED / projection
    "video technician", "led technician", "projectionist",
    "projection technician", "camera operator", "shader",
    "video operator", "media server",
    # show control
    "show control", "technical director",
    # staging / rigging / production
    "stagehand", "stage manager", "rigger", "rigging",
    "production technician", "stage technician",
    # broadcast (augment)
    "broadcast technician", "studio engineer", "master control",
    "broadcast maintenance",
    # general live events
    "live event", "event production",
    # RF / wireless
    "rf technician", "rf coordinator",
    # playback
    "playback engineer", "playback operator",
    # AV installation / low voltage
    "av installer", "low voltage",
    # venue / house
    "house engineer", "venue technician",
    # replay / EVS / graphics
    "replay operator", "evs operator", "graphics operator",
    # misc disciplines
    "systems engineer",
    "event rigger",
    "master electrician", "theatrical electrician",
    "scenic",
    # streaming / virtual events
    "streaming engineer", "streaming technician", "webcast", "zoom producer",
    "virtual event", "hybrid event", "livestream",
    # AV/IT crossover
    "av/it", "collaboration engineer", "unified communications",
    # sound system / corporate / hotel
    "sound system", "pa engineer", "corporate av", "hotel av",
    "in-house av", "banquet av",
    # automation
    "automation operator", "stage automation",
    # touring
    "touring engineer", "backline tech", "concert production",
    # comms / intercom
    "comms tech", "intercom tech",
    # post-production
    "post engineer", "post-production",
    # video engineering
    "engineer in charge", "eic", "dit", "ccu operator",
    # production management
    "technical producer", "show caller", "production coordinator",
}

IRRELEVANT_TITLE_KEYWORDS = {
    "software engineer", "data analyst", "data engineer", "data scientist",
    "warehouse", "forklift", "truck driver", "nurse", "medical",
    "accountant", "financial analyst", "marketing manager", "sales representative",
    "recruiter", "hr manager", "human resources", "supply chain",
    "mechanical engineer", "civil engineer", "chemical engineer",
    "cloud engineer", "devops", "machine learning", "ml engineer",
    "full stack", "frontend", "backend", "ios developer", "android developer",
    "product manager", "program manager", "scrum master",
    "cybersecurity", "dental", "pharmacy", "pharmacist",
    "veterinary", "real estate", "insurance agent",
    "plumber", "hvac technician", "automotive",
    "radiologist", "occupational therapist",
}

AV_DESCRIPTION_TERMS = {
    "dante", "crestron", "extron", "qsys", "q-sys", "biamp", "shure",
    "polycom", "cisco webex", "zoom rooms", "teams rooms", "aver",
    "kramer", "atlona", "lightware", "qsc", "harman", "bss",
    "audinate", "sdi", "ndi", "st2110", "st 2110", "tricaster",
    "vmix", "blackmagic", "aja", "ross video", "newtek",
    "allen & heath", "yamaha cl", "yamaha pm", "digico", "midas",
    "avid venue", "soundcraft", "presonus", "pro tools",
    "conference room", "huddle room", "boardroom", "ballroom",
    "av rack", "signal flow", "codec", "dsp", "matrix switcher",
    # lighting brands & tech
    "etc eos", "grandma", "grandma2", "grandma3", "ma lighting",
    "wholehog", "hog 4", "avolites", "chamsys", "moving light",
    "conventional fixture", "followspot", "dimmer rack",
    "martin lighting", "robe lighting", "chauvet",
    # video / LED brands & tech
    "disguise", "resolume", "notch", "brompton", "novastar",
    "barco", "christie", "led wall", "led processor",
    "media server", "panasonic projector",
    # show control
    "qlab", "medialon", "watchout", "pandoras box",
    "show control", "timecode", "smpte", "ltc",
    # staging / rigging
    "truss", "chain motor", "ground support", "line array",
    "rigging", "scenic",
    # RF / wireless
    "rf coordination", "frequency coordination", "wireless microphone",
    "antenna distribution", "in-ear monitor", "shure axient",
    "wisycom", "lectrosonics",
    # playback
    "playback", "ableton",
    # AV installation / low voltage
    "low voltage", "av installation", "commissioning", "rack build",
    # replay / EVS / graphics
    "evs", "replay", "viz engine", "chyron",
    # venue / installed
    "house mix", "installed sound",
    # scenic
    "scenic shop", "set construction",
    # streaming / virtual events
    "vmix", "obs studio", "webcast", "rtmp", "encoder",
    "zoom producer", "livestream", "webinar",
    # AV/IT crossover
    "teams rooms", "zoom rooms", "av network",
    # comms / intercom
    "clear-com", "rts intercom", "riedel", "bolero", "partyline",
    # automation
    "kinesys", "navigator", "stage automation", "chain hoist",
    # touring
    "tour production", "backline", "advance", "road crew",
    # post-production
    "davinci resolve", "premiere pro", "after effects",
    # measurement / alignment
    "smaart", "system tuning", "alignment",
    # additional brands
    "analog way", "green hippo", "hippotizer",
    "robe", "ayrton", "elation",
    "d&b audiotechnik", "l-acoustics", "meyer sound",
    "solid state logic", "ssl",
}

# Known target companies that should always pass
TARGET_COMPANY_KEYWORDS = {
    "avi-spl", "diversified", "avispl", "crestron", "extron", "harman",
    "shure", "biamp", "qsc", "encore", "psav",
    "prg", "4wall", "solotech", "neg earth",
    "christie", "barco", "freeman", "live nation",
}

# Per-user pre-filter: expand target_roles into related terms
ROLE_EXPANSIONS = {
    "audio": {"sound", "a1", "a2", "dante", "mixing", "rf", "foh", "monitor engineer",
              "comms", "live sound", "foh engineer", "monitor tech", "system tech"},
    "video": {"camera", "led", "projection", "projectionist", "switching", "shader",
              "vme", "media server", "disguise", "resolume", "led wall",
              "replay operator", "evs operator", "graphics operator",
              "dit", "eic", "ccu operator", "streaming", "virtual production"},
    "broadcast": {"studio", "transmission", "on-air", "master control", "playout",
                  "studio engineer", "broadcast operations",
                  "broadcast maintenance", "replay operator", "evs operator", "graphics operator",
                  "mcr", "toc", "broadcast it"},
    "av": {"audiovisual", "audio-visual", "a/v", "conference room", "huddle",
           "av integration", "unified communications"},
    "lighting": {"ld", "lighting designer", "lighting technician", "dimmer",
                 "moving light", "followspot", "grandma", "etc eos", "hog",
                 "lighting programmer", "lighting director", "spot operator",
                 "previz", "wysiwyg", "ma3", "console programmer"},
    "event": {"event technology", "conference services", "live event",
              "event production", "stagehand"},
    # Multi-word discipline keys
    "show control": {"qlab", "medialon", "watchout", "pandoras box",
                     "timecode", "smpte", "show programmer"},
    "projection": {"projectionist", "media server", "barco", "christie",
                   "disguise", "resolume", "notch"},
    "stage": {"stagehand", "stage manager", "stage technician",
              "technical director", "production technician"},
    "rigging": {"rigger", "truss", "chain motor", "fly system",
                "ground support", "scenic"},
    # New discipline keys
    "rf": {"rf technician", "rf coordinator", "frequency coordination",
           "wireless microphone", "antenna distribution", "shure axient",
           "wisycom", "lectrosonics", "in-ear monitor"},
    "playback": {"playback engineer", "playback operator", "ableton",
                 "media server", "disguise", "resolume"},
    "install": {"av installer", "low voltage", "av installation",
                "commissioning", "rack build", "systems engineer",
                "dsp programmer", "control programmer", "crestron programmer"},
    "scenic": {"scenic shop", "set construction", "scenic carpenter",
               "scenic artist", "scenic charge"},
    "electrician": {"master electrician", "theatrical electrician",
                    "dimmer", "power distribution", "followspot"},
    # --- New discipline keys (Fix 6) ---
    "streaming": {"vmix", "obs", "webcast", "streaming technician", "zoom producer",
                  "encoder", "rtmp", "ndi", "livestream", "webinar producer",
                  "streaming engineer", "live stream"},
    "virtual events": {"virtual event", "hybrid event", "webcast", "zoom producer",
                       "streaming technician", "virtual production", "encoder"},
    "av/it": {"av/it", "av it", "network av", "dante network", "it av",
              "collaboration engineer", "unified communications", "teams rooms",
              "zoom rooms", "av network"},
    "foh": {"foh engineer", "front of house", "foh", "house engineer",
            "house sound", "live sound", "pa engineer"},
    "system tech": {"system tech", "systems technician", "system engineer",
                    "pa tech", "sound system tech", "rf tech"},
    "corporate av": {"corporate av", "corporate audiovisual", "conference room",
                     "boardroom", "huddle room", "hotel av", "ballroom",
                     "event technology", "meeting technology"},
    "hotel av": {"hotel av", "hotel audiovisual", "in-house av", "ballroom",
                 "banquet av", "convention center", "encore", "psav",
                 "pinnacle live"},
    "automation": {"kinesys", "navigator", "stage automation", "motion control",
                   "fly system", "automation operator", "chain hoist"},
    "touring": {"tour manager", "production manager", "backline tech", "advance",
                "touring engineer", "touring crew", "road crew", "tour production",
                "concert production"},
    "comms": {"clear-com", "rts", "riedel", "intercom", "bolero", "partyline",
              "comms tech", "communications tech"},
    "intercom": {"clear-com", "rts", "riedel", "intercom", "bolero", "partyline",
                 "intercom tech", "comms tech"},
    "post-production": {"davinci resolve", "premiere", "after effects",
                        "post-production", "color grading", "finishing",
                        "edit suite", "post engineer"},
    "video engineering": {"video engineer", "eic", "engineer in charge",
                          "dit", "ccu operator", "shader", "video operator",
                          "media server", "led processor"},
    "production": {"production coordinator", "production assistant", "producer",
                   "production manager", "show caller", "stage manager",
                   "technical producer"},
}


# ---------------------------------------------------------------------------
# Per-user pre-filter
# ---------------------------------------------------------------------------

def user_prefilter(jobs: list[JobListing], user: dict) -> tuple[list[JobListing], list[JobListing]]:
    """
    Fast keyword-based per-user pre-filter. Checks job title/description against
    the user's target_roles to skip clearly irrelevant jobs before expensive LLM eval.
    Returns (relevant_jobs, skipped_jobs).
    """
    target_roles = user.get("target_roles") or []
    if not target_roles:
        return jobs, []

    # Build keyword set from target roles + expansions
    role_keywords = set()
    for role in target_roles:
        role_lower = role.lower()
        tokens = role_lower.split()
        role_keywords.update(tokens)
        # Check individual tokens
        for token in tokens:
            if token in ROLE_EXPANSIONS:
                role_keywords.update(ROLE_EXPANSIONS[token])
        # Check contiguous 2-word phrases for multi-word keys like "show control"
        for i in range(len(tokens) - 1):
            phrase = f"{tokens[i]} {tokens[i+1]}"
            if phrase in ROLE_EXPANSIONS:
                role_keywords.update(ROLE_EXPANSIONS[phrase])
        # Check full role string
        if role_lower in ROLE_EXPANSIONS:
            role_keywords.update(ROLE_EXPANSIONS[role_lower])

    relevant, skipped = [], []
    for job in jobs:
        title_lower = job.title.lower()
        company_lower = job.company.lower()
        desc_lower = (job.description or "").lower()

        # Known AV company -> always pass
        if any(kw in company_lower for kw in TARGET_COMPANY_KEYWORDS):
            relevant.append(job)
            continue

        # Title contains any role keyword -> pass
        if any(kw in title_lower for kw in role_keywords):
            relevant.append(job)
            continue

        # Description contains 2+ role-specific terms -> pass
        if desc_lower:
            desc_hits = sum(1 for kw in role_keywords if kw in desc_lower)
            if desc_hits >= 2:
                relevant.append(job)
                continue

        skipped.append(job)

    roles_str = ", ".join(target_roles)
    log.info(f"Per-user pre-filter: {len(relevant)} relevant, {len(skipped)} skipped (target_roles: {roles_str})")
    return relevant, skipped


# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------

def _keyword_score_job(job: JobListing) -> tuple[float, list[str]]:
    """Score a job based on keyword relevance. Returns (score 0-1, matched_keywords)."""
    title_lower = job.title.lower()
    company_lower = job.company.lower()
    desc_lower = (job.description or "").lower()
    matched = []

    # Check for irrelevant title keywords first (strong negative signal)
    # Use word-boundary regex to avoid false positives like "product manager" matching "production manager"
    # Returns -1.0 sentinel = confirmed irrelevant (distinct from 0.0 = no signal)
    # BUT: rescue titles that also contain AV-relevant terms (send to LLM instead of killing)
    for kw in IRRELEVANT_TITLE_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
            # Check if title also contains AV-relevant terms -- if so, it's ambiguous, not irrelevant
            has_av_signal = any(rkw in title_lower for rkw in RELEVANT_TITLE_KEYWORDS)
            if not has_av_signal and desc_lower:
                # Also check description for AV terms before killing
                desc_av_hits = sum(1 for t in AV_DESCRIPTION_TERMS if t in desc_lower)
                if desc_av_hits >= 2:
                    has_av_signal = True
            if has_av_signal:
                matched.append(f"ambiguous:{kw}+av")
                return 0.3, matched  # ambiguous -> goes to LLM pre-filter
            if not desc_lower:
                # No description to check -- can't confirm irrelevant, route to LLM
                matched.append(f"ambiguous:{kw}+no_desc")
                return 0.3, matched
            return -1.0, [f"-{kw}"]

    # Target company = automatic pass
    for kw in TARGET_COMPANY_KEYWORDS:
        if kw in company_lower:
            matched.append(f"company:{kw}")
            return 1.0, matched

    score = 0.0

    # Title keyword match (strong signal)
    for kw in RELEVANT_TITLE_KEYWORDS:
        if kw in title_lower:
            score += 0.4
            matched.append(f"title:{kw}")

    # Description keyword density (moderate signal)
    if desc_lower:
        desc_hits = 0
        for term in AV_DESCRIPTION_TERMS:
            if term in desc_lower:
                desc_hits += 1
                matched.append(term)
        if desc_hits >= 3:
            score += 0.4
        elif desc_hits >= 1:
            score += 0.2

    return min(score, 1.0), matched


# ---------------------------------------------------------------------------
# LLM pre-filter for ambiguous jobs
# ---------------------------------------------------------------------------

def _llm_pre_filter(config: dict, jobs: list[JobListing]) -> list[tuple[JobListing, bool, str]]:
    """Run cheap LLM pre-filter on ambiguous jobs. Returns list of (job, passed, reason)."""
    provider, model = resolve_model(config, "pre_filter")
    log.info(f"Pre-filter LLM: using {provider}/{model} for {len(jobs)} ambiguous jobs")

    # Get the appropriate API key
    key_map = {
        "openrouter": "openrouter_key",
        "google_aistudio": "google_aistudio_key",
        "anthropic": "anthropic_key",
        "openai_compatible": "openai_compatible_key",
    }
    api_key = config.get(key_map.get(provider, "openrouter_key"), "")
    if not api_key:
        log.warning(f"Pre-filter: no API key for {provider} — marking all ambiguous as passed")
        return [(j, True, "no LLM key") for j in jobs]

    results = []

    def _call_llm(job: JobListing) -> tuple[bool, str]:
        import time as _time
        from pipeline_utils import log_api_usage
        prompt = (
            f"Job title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Description excerpt: {(job.description or '')[:500]}\n\n"
            "Is this job relevant to ANY AV/live events/broadcast professional? "
            "Relevant disciplines include: audiovisual engineer, broadcast engineer, "
            "AV technician, event technology, live sound, corporate AV, "
            "conference room technology, lighting designer, lighting technician, "
            "video engineer, LED technician, projection technician, show control, "
            "stagehand, rigger, technical director, stage manager, "
            "production technician, RF technician, RF coordinator, "
            "playback engineer, playback operator, master electrician, "
            "theatrical electrician, AV installer, low voltage technician, "
            "broadcast maintenance engineer, house engineer, venue technician, "
            "EVS operator, replay operator, graphics operator, "
            "scenic carpenter, event rigger, systems engineer. "
            "Reply YES or NO with a 1-sentence reason."
        )
        try:
            _start = _time.time()
            _pt, _ct = 0, 0
            if provider == "google_aistudio":
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=15,
                )
                resp.raise_for_status()
                rj = resp.json()
                text = rj["candidates"][0]["content"]["parts"][0]["text"].strip()
                um = rj.get("usageMetadata", {})
                _pt = um.get("promptTokenCount", 0)
                _ct = um.get("candidatesTokenCount", 0)
            else:
                base_url = "https://openrouter.ai/api/v1" if provider == "openrouter" else config.get("openai_compatible_base_url", "")
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 100},
                    timeout=15,
                )
                resp.raise_for_status()
                rj = resp.json()
                text = rj["choices"][0]["message"]["content"].strip()
                usage = rj.get("usage", {})
                _pt = usage.get("prompt_tokens", 0)
                _ct = usage.get("completion_tokens", 0)

            _latency = int((_time.time() - _start) * 1000)
            log_api_usage(
                source="pipeline", category="llm", pipeline="job_scraper", operation="pre_filter",
                provider=provider, model=model,
                prompt_tokens=_pt, completion_tokens=_ct, total_tokens=_pt + _ct,
                latency_ms=_latency, success=True,
            )
            passed = text.upper().startswith("YES")
            return passed, text[:200]
        except Exception as e:
            log.debug(f"Pre-filter LLM failed for {job.title}: {e}")
            return True, f"LLM error: {e}"  # Default to pass on error

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(_call_llm, j): j for j in jobs}
        for future in as_completed(future_map):
            job = future_map[future]
            try:
                passed, reason = future.result()
            except Exception:
                passed, reason = True, "error"
            results.append((job, passed, reason))

    return results


# ---------------------------------------------------------------------------
# Main pre-filter orchestrator
# ---------------------------------------------------------------------------

def run_pre_filter(config: dict, jobs: list[JobListing]):
    """
    Two-layer pre-filter: keyword scoring + cheap LLM for ambiguous jobs.
    Updates pre_filter_score, pre_filter_passed, title_keywords in Supabase.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return

    headers = _supabase_headers(supabase_key)

    console.print(f"\n[bold]Pre-filtering {len(jobs)} jobs...[/bold]")

    # Layer 1: keyword scoring
    # score >= 0.7   -> clear_pass  (pre_filter_passed=True)
    # score < 0      -> clear_fail  (confirmed irrelevant by IRRELEVANT_TITLE_KEYWORDS)
    # 0 < score < 0.7 -> ambiguous  -> send to LLM
    # score == 0.0   -> no_signal   -> send to LLM (NOT killed -- "no hits" != "irrelevant")
    clear_pass = []
    clear_fail = []
    ambiguous = []
    no_signal = []

    for job in jobs:
        score, keywords = _keyword_score_job(job)
        # Store non-negative score for Supabase (sentinel -1.0 -> 0.0)
        job._pf_score = max(score, 0.0)
        job._pf_keywords = keywords
        if score >= 0.7:
            clear_pass.append(job)
        elif score < 0:
            clear_fail.append(job)
        elif score == 0.0:
            no_signal.append(job)
        else:
            ambiguous.append(job)

    console.print(
        f"  Keywords: {len(clear_pass)} pass, {len(clear_fail)} fail, "
        f"{len(ambiguous)} ambiguous, {len(no_signal)} no-signal"
    )

    # Layer 2: cheap LLM for ambiguous + no-signal jobs
    llm_candidates = ambiguous + no_signal
    llm_results = {}
    if llm_candidates:
        # Check if pre_filter model is configured
        models = config.get("models", {})
        if models.get("pre_filter", {}).get("model"):
            llm_out = _llm_pre_filter(config, llm_candidates)
            for job, passed, reason in llm_out:
                llm_results[job.job_id] = (passed, reason)
            llm_passed = sum(1 for _, p, _ in llm_out if p)
            console.print(f"  LLM: {llm_passed}/{len(llm_candidates)} candidates passed ({len(ambiguous)} ambiguous + {len(no_signal)} no-signal)")
        else:
            # No LLM configured: ambiguous pass, no-signal also pass (conservative -- keep for per-user eval)
            console.print(f"  [dim]No pre_filter model configured — passing all {len(llm_candidates)} candidates ({len(ambiguous)} ambiguous + {len(no_signal)} no-signal)[/dim]")
            for job in llm_candidates:
                llm_results[job.job_id] = (True, "no model configured")

    # Build update payloads and batch-update Supabase
    stats = {"total": len(jobs), "passed": 0, "failed": 0, "no_signal": len(no_signal), "llm_called": len(llm_candidates)}
    BATCH = 50

    all_updates = []
    for job in jobs:
        score = getattr(job, "_pf_score", 0.0)
        keywords = getattr(job, "_pf_keywords", [])

        if job in clear_pass:
            passed = True
        elif job in clear_fail:
            passed = False
        else:
            passed = llm_results.get(job.job_id, (True, ""))[0]

        if passed:
            stats["passed"] += 1
        else:
            stats["failed"] += 1

        all_updates.append({
            "job_id": job.job_id,
            "pre_filter_score": round(score, 3),
            "pre_filter_passed": passed,
            "title_keywords": keywords[:20],  # cap array size
        })

    # Update pre-filter columns on existing rows (PATCH, not upsert)
    failed = 0
    for update in all_updates:
        job_id = update["job_id"]
        payload = {k: v for k, v in update.items() if k != "job_id"}
        try:
            requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                headers=headers,
                json=payload,
                timeout=10,
            ).raise_for_status()
        except Exception:
            failed += 1
    if failed:
        log.warning(f"Pre-filter: {failed}/{len(all_updates)} updates failed")

    console.print(f"  [bold green]Pre-filter complete:[/bold green] {stats['passed']} passed, {stats['failed']} filtered out")
    return stats


# ---------------------------------------------------------------------------
# Re-filter backfilled jobs
# ---------------------------------------------------------------------------

def refilter_backfilled_jobs(config: dict):
    """
    Re-run pre-filter on jobs that were previously killed (pre_filter_passed=false)
    but now have descriptions (backfilled after initial failure). Gives these jobs
    a second chance now that their descriptions are available.
    """
    supabase_url = os.environ.get("SUPABASE_URL") or config.get("supabase_url", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or config.get("supabase_service_role_key", "")
    if not supabase_url or not supabase_key:
        return 0

    headers = _supabase_headers(supabase_key)

    # Find jobs that failed pre-filter but now have descriptions
    resp = requests.get(
        f"{supabase_url}/rest/v1/jobs"
        f"?pre_filter_passed=eq.false"
        f"&description=not.is.null"
        f"&listing_status=eq.active"
        f"&select=job_id,title,company,location,url,source,description,salary,date_posted,tier"
        f"&limit=500",
        headers=headers, timeout=30,
    )
    if not resp.ok:
        log.warning(f"Refilter: failed to query candidates: {resp.status_code}")
        return 0

    candidates = resp.json()
    if not candidates:
        return 0

    # Convert to JobListing objects for run_pre_filter
    refilter_jobs = []
    for row in candidates:
        job = JobListing(
            title=row.get("title", ""),
            company=row.get("company", ""),
            location=row.get("location", ""),
            url=row.get("url", ""),
            source=row.get("source", ""),
            description=row.get("description", ""),
            salary=row.get("salary", "") or "",
            date_posted=row.get("date_posted", "") or "",
            tier=row.get("tier", "") or "",
        )
        # Force job_id to match existing record
        job.job_id = row["job_id"]
        refilter_jobs.append(job)

    console.print(f"[bold]Re-filtering {len(refilter_jobs)} previously-killed jobs with new descriptions...[/bold]")
    stats = run_pre_filter(config, refilter_jobs)
    newly_passed = (stats or {}).get("passed", 0)
    if newly_passed:
        console.print(f"  Rescued {newly_passed} jobs that now pass pre-filter with descriptions")
    return newly_passed
