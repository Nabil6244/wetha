from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

MAX_VISUAL_SCENES = 1500


class Advisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    provider: Literal["NHC", "NWS", "TRAINING"]
    event_key: str
    title: str
    issued_at: datetime
    expires_at: datetime | None = None
    source_url: str
    provenance: Literal["official_fetch", "manual_import", "synthetic_fixture"]
    severity: str = "Unknown"
    area: str = ""
    facts: dict[str, str | float | int | None] = Field(default_factory=dict)
    text: str
    checksum: str = ""
    references: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    forecast_excerpt: str | None = None
    source_feed_url: str | None = None
    source_payload: dict | None = None

    @field_validator("issued_at", "expires_at")
    @classmethod
    def aware_utc(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Source timestamps must include a timezone.")
        return value.astimezone(timezone.utc)


class ImportRequest(BaseModel):
    text: str = Field(min_length=100, max_length=100_000)
    source_url: str = Field(max_length=1000)


class FetchRequest(BaseModel):
    source_url: str = Field(max_length=1000)


class ScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    advisory_id: str
    advisory_ids: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def selected_sources(self):
        if len(set(self.advisory_ids)) != len(self.advisory_ids):
            raise ValueError('Select each advisory only once.')
        if self.advisory_ids and self.advisory_ids[0] != self.advisory_id:
            raise ValueError('The primary advisory must be the first selected source.')
        return self

    engine: Literal['deterministic', 'ollama', 'gemini'] = 'deterministic'
    refresh_sources: bool = False
    bulletin: bool = False
    target_minutes: Literal[10,20,30,60] = 10


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=2, max_length=100)
    expected_revision: int | None = Field(default=None, ge=1)
    note: str = Field(default='', max_length=2000)

    @field_validator('reviewer')
    @classmethod
    def named(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('A reviewer name is required.')
        return value.strip()


class EditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    text: str = Field(min_length=50, max_length=60_000)
    editor: str = Field(min_length=2, max_length=100)
    note: str = Field(default='Narration edited', max_length=2000)

    @field_validator('note')
    @classmethod
    def revision_note(cls, value):
        return value.strip() or 'Narration edited'

    @field_validator('editor')
    @classmethod
    def not_blank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('An editor name is required.')
        return value.strip()


class ClaimSupportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    claim_id: str
    advisory_id: str
    quote: str = Field(min_length=20, max_length=15_000)
    explanation: str = Field(min_length=10, max_length=2000)
    reviewer: str = Field(min_length=2, max_length=100)

    @field_validator('reviewer', 'explanation')
    @classmethod
    def not_blank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('Named source verification and an explanation are required.')
        return value.strip()


class Change(BaseModel):
    field: str
    previous: str | float | int | None
    current: str | float | int | None
    delta: float | None = None


class PollingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    interval_seconds: int = Field(default=300, ge=60, le=3600)


class VisualPlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    script_id: str
    expected_revision: int = Field(ge=1)
    style: Literal['map','satellite','radar'] = 'map'


class SceneImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csv_text: str = Field(min_length=100, max_length=500_000)


class MediaImportMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=180)
    kind: Literal['image', 'video', 'audio']
    context: Literal['illustrative', 'archival', 'narration']
    license: str = Field(min_length=3, max_length=2000)
    attribution: str = Field(min_length=2, max_length=500)
    source: str = Field(min_length=2, max_length=1000)
    rights_confirmed: Literal[True]
    source_provider: Literal['local', 'stock', 'youtube'] = 'local'
    reuse_basis: Literal['permission', 'cc_by', 'creator_owned', 'stock_license', 'public_domain'] | None = None
    reuse_evidence: str = Field(default='', max_length=2000)
    preferred_clip_seconds: float = Field(default=3.5, ge=3, le=4)

    @model_validator(mode='after')
    def youtube_source(self):
        if self.source_provider != 'youtube':
            return self
        import re
        from urllib.parse import urlsplit, parse_qs
        parsed = urlsplit(self.source)
        if self.kind != 'video':
            raise ValueError('YouTube sources require a local video file.')
        if parsed.scheme != 'https' or parsed.port is not None or parsed.username or parsed.password:
            raise ValueError('Use the original HTTPS YouTube video URL.')
        video_id = None
        if parsed.hostname == 'youtu.be':
            video_id = parsed.path.removeprefix('/')
        elif parsed.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            if parsed.path == '/watch':
                values = parse_qs(parsed.query).get('v', [])
                video_id = values[0] if len(values) == 1 else None
            elif re.fullmatch(r'/(shorts|live|embed)/[A-Za-z0-9_-]{11}', parsed.path):
                video_id = parsed.path.rsplit('/', 1)[-1]
        if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError('Choose a YouTube video URL, not a channel, playlist or another website.')
        if self.reuse_basis not in ('permission', 'cc_by', 'creator_owned') or len(self.reuse_evidence.strip()) < 10:
            raise ValueError('Record creator permission, CC BY evidence or ownership, with a reference or explanation.')
        self.source = 'https://www.youtube.com/watch?v=' + video_id
        self.reuse_evidence = self.reuse_evidence.strip()
        return self

    @field_validator('license', 'attribution', 'source')
    @classmethod
    def nonempty(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('License, attribution and provenance are required.')
        return value.strip()


class FootageCutRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    media_id: str
    seconds: float = Field(ge=3, le=4)
    trim_start: float = Field(default=0, ge=0, le=3600)


class ProductionSceneRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str
    seconds: float = Field(ge=1, le=120)
    media_id: str | None = None
    trim_start: float = Field(default=0, ge=0, le=3600)
    transition: Literal['cut', 'fade'] = 'cut'
    cuts: list[FootageCutRequest] = Field(default_factory=list, max_length=30)
    map_mode: Literal['auto','track','warnings','radar','forecast'] = 'auto'
    regional_focus: str = Field(default='auto', max_length=4)

    @field_validator('regional_focus')
    @classmethod
    def valid_region(cls, value):
        from .regional import options
        if value != 'auto' and value not in {r['code'] for r in options()}:
            raise ValueError('Choose a supported state or automatic script focus.')
        return value

    graphic_style: Literal['auto','change_gauge','comparison_split','advisory_timeline','forecast_clock','question_reveal','source_card'] = 'auto'


class TimelineRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str
    title: str = Field(min_length=2, max_length=150)
    scenes: list[ProductionSceneRequest] = Field(min_length=1, max_length=MAX_VISUAL_SCENES)
    narration_id: str | None = None
    alignment_id: str | None = None
    narration_verified: bool = False
    satellite_context: bool = False
    presentation: Literal['captioned', 'cinematic', 'broadcast'] = 'captioned'
    automatic_graphs: bool = True
    music: bool = False
    # With imported narration: a quiet original instrumental that ducks under the voice, plus soft transition sounds.
    music_bed: bool = True
    template: Literal['short_30', 'report_60', 'report_90'] | None = None


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    timeline_id: str


class MediaCatalogRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    tags: list[str] = Field(default_factory=list, max_length=30)
    event_id: str = Field(default='', max_length=80)
    location: str = Field(default='', max_length=150)
    region_codes: list[str] = Field(default_factory=list, max_length=10)
    location_reviewed: bool = False
    captured_at: date | None = None
    reference: str = Field(default='', max_length=1000)
    preferred_trim_start: float = Field(default=0, ge=0, le=3600)

    @model_validator(mode='after')
    def region_review(self):
        from .regional import options
        from urllib.parse import urlsplit
        allowed = {r['code'] for r in options()}
        self.region_codes = sorted(set(self.region_codes))
        if any(code not in allowed for code in self.region_codes):
            raise ValueError('Unsupported capture region.')
        if self.location_reviewed:
            parsed = urlsplit(self.reference)
            if not self.region_codes or parsed.scheme not in ('https', 'http') or not parsed.hostname:
                raise ValueError('Reviewed locations require a capture region and a source URL documenting it.')
        return self

    @field_validator('tags')
    @classmethod
    def clean_tags(cls, values):
        result = sorted({v.strip().lower() for v in values if v.strip()})
        if any(len(v) > 50 for v in result):
            raise ValueError('Media tags are limited to 50 characters.')
        return result


class ProductionAssistRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    regional_focus: dict[str,str] = Field(default_factory=dict, max_length=120)
    plan_id: str
    template: Literal['short_30', 'report_60', 'report_90'] = 'short_30'


class ChapterAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter_id: str
    timeline_ids: list[str] = Field(default_factory=list, max_length=30)


class LongformCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapters: list[ChapterAssignment] = Field(default_factory=list, max_length=12)


class MediaDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(default='storm', min_length=2, max_length=160)
    provider: Literal['all', 'stock', 'youtube', 'commons'] = 'all'
    kind: Literal['video', 'image', 'all'] = 'video'
    plan_id: str | None = None
    live: bool = True


class DiscoveryImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    rights_confirmed: Literal[True]

class PolishedRequest(EditRequest):
    sources: list[str] = Field(default_factory=list, max_length=600)

class SourceMapRequest(BaseModel):
    text: str = Field(min_length=50, max_length=60_000)

class AlignmentRequest(BaseModel):
    plan_id: str
    narration_id: str

class FootageExpansionRequest(BaseModel):
    plan_id: str
    max_new_clips: int = Field(default=12, ge=1, le=24)
