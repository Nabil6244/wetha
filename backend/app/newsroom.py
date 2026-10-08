from typing import Protocol
from uuid import uuid4
from .contracts import Advisory
from .weather import changes, freshness


class ScriptWriter(Protocol):
    def generate(self, advisory: Advisory, previous: Advisory | None) -> dict: ...


class VoiceEngine(Protocol):
    def synthesize(self, text: str, output_path: str) -> dict: ...


class VisualRenderer(Protocol):
    def render(self, scene: dict, output_path: str) -> dict: ...


class BroadcastController(Protocol):
    def status(self) -> dict: ...


class GroundedScriptWriter:
    """Deterministic source-to-script baseline; no invented forecasts or LLM dependencies."""
    def generate(self, advisory: Advisory, previous: Advisory | None) -> dict:
        label = freshness(advisory)
        if label == "current" and previous and previous.provenance != "official_fetch":
            label = "unverified"
        stamp = advisory.issued_at.strftime("%B %d, %Y at %H:%M UTC")
        warning = {"training":"TRAINING ONLY. This synthetic scenario is not a weather observation.",
            "historical":"ARCHIVAL REPORT. This advisory is historical and must not be broadcast as current weather.",
            "expired":"EXPIRED ADVISORY. This warning is no longer valid.",
            "unverified":"UNVERIFIED IMPORT. Confirm every fact against the original advisory.",
            "non-operational":"NON-OPERATIONAL ALERT. This may be a test or a cancellation; do not air as an active warning.",
            "current":"PRERECORDED REPORT. Recheck the official advisory before broadcast."}[label]
        paragraphs = [warning, f"According to {'the National Hurricane Center' if advisory.provider == 'NHC' else 'the National Weather Service' if advisory.provider == 'NWS' else 'the synthetic training dataset'}, {advisory.title} was issued on {stamp}."]
        if "wind_mph" in advisory.facts:
            f = advisory.facts
            paragraphs.append(f"The advisory reports maximum sustained winds of {f['wind_mph']} miles per hour and a minimum central pressure of {f['pressure_mb']} millibars. The reported center is at latitude {f['latitude']} and longitude {f['longitude']}.")
        else:
            paragraphs.append(f"Affected area: {advisory.area}.\n{advisory.text}")
        difference = changes(previous, advisory)
        if previous:
            readable = {"wind_mph": ("maximum sustained winds", "mph"), "pressure_mb": ("central pressure", "mb"), "latitude": ("latitude", "degrees"), "longitude": ("longitude", "degrees")}
            lines = [f"Compared with the advisory issued at {previous.issued_at.strftime('%H:%M UTC on %B %d, %Y')}:"]
            for change in difference:
                name, units = readable.get(change.field, (change.field.replace('_', ' '), ""))
                lines.append(f"{name.capitalize()} changed from {change.previous} to {change.current} {units}.")
            if not difference:
                lines.append("No changes were detected in the extracted measurements.")
            paragraphs.append(" ".join(lines))
        paragraphs.append("Follow official local guidance. This draft does not add a forecast, storm track, or impacts beyond the source information.")
        source_refs = [advisory.source_url] + ([previous.source_url] if previous else [])
        text = "\n\n".join(paragraphs)
        return {"id":str(uuid4()), "advisory_id":advisory.id, "source_advisory_ids":[advisory.id] + ([previous.id] if previous else []), "title":advisory.title, "text":text, "status":"needs_review", "source_refs":source_refs,
            "source_issued_at":advisory.issued_at.isoformat(), "source_expires_at":advisory.expires_at.isoformat() if advisory.expires_at else None,
            "label":label, "engine":"deterministic-v1", "estimated_seconds":round(len(text.split()) / 145 * 60), "actual_audio_seconds":None,
            "broadcast_eligible":False, "review_required":True,
            "qc":[{"check":"Source provenance", "passed":advisory.provenance == "official_fetch" and (previous is None or previous.provenance == "official_fetch")}, {"check":"Source freshness", "passed":label == "current"}, {"check":"Human editorial review", "passed":False}, {"check":"Audio and rendered video", "passed":False}],
            "scenes":[{"id":f"scene-{index+1}", "type":"lower_third", "script_segment":paragraph, "target_seconds":round(len(paragraph.split()) / 145 * 60, 1),
                "timing_basis":"estimate; audio not generated", "source_refs":source_refs, "advisory_timestamp":advisory.issued_at.isoformat(),
                "camera_movement":"none", "transition":"cut", "fallback_asset":None, "voiceover_alignment":None,
                "parameters":{"label":label}, "visual_instructions":"Show source and issue timestamp; label training and archival material explicitly."} for index, paragraph in enumerate(paragraphs)]}
