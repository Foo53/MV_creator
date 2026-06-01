from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from mv_creator.models import CharacterProfile, ImagePrompt, RAGTraceItem, ShotPlan


@dataclass
class MemoryRecord:
    id: str
    kind: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


class RAGStore:
    """制作情報を保存し、後続エージェントへ渡す簡易RAGストア。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[MemoryRecord] = []
        self.trace: list[RAGTraceItem] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.records = [MemoryRecord(**item) for item in data.get("records", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"records": [record.__dict__ for record in self.records]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, record: MemoryRecord) -> None:
        self.records = [item for item in self.records if item.id != record.id]
        self.records.append(record)

    def add_character(self, character: CharacterProfile) -> None:
        self.add(
            MemoryRecord(
                id=f"character:{character.id}",
                kind="character",
                text=(
                    f"{character.name}: {character.role}. Personality: {character.personality}. "
                    f"Appearance: {character.appearance}. Wardrobe: {character.wardrobe}. "
                    f"Continuity: {'; '.join(character.continuity_notes)}"
                ),
                metadata={"character_id": character.id},
            )
        )

    def add_shot(self, shot: ShotPlan) -> None:
        self.add(
            MemoryRecord(
                id=f"shot:{shot.shot_id}",
                kind="shot",
                text=(
                    f"{shot.shot_id} in {shot.scene_id}: {shot.description}. Camera: {shot.camera}. "
                    f"Motion start: {shot.motion_start}. Motion end: {shot.motion_end}. Lighting: {shot.lighting}."
                ),
                metadata={"shot_id": shot.shot_id, "scene_id": shot.scene_id},
            )
        )

    def add_prompt(self, prompt: ImagePrompt) -> None:
        self.add(
            MemoryRecord(
                id=f"prompt:{prompt.shot_id}",
                kind="prompt",
                text=f"Image prompt for {prompt.shot_id}: {prompt.prompt}. Negative: {prompt.negative_prompt}",
                metadata={"shot_id": prompt.shot_id},
            )
        )

    def search(self, query: str, *, used_by: str, limit: int = 5) -> list[MemoryRecord]:
        query_terms = set(_tokens(query))
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self.records:
            score = len(query_terms.intersection(_tokens(record.text)))
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = [record for _, record in scored[:limit]]
        self.trace.append(RAGTraceItem(query=query, results=[record.id for record in results], used_by=used_by))
        return results

    def context_block(self, query: str, *, used_by: str, limit: int = 5) -> str:
        results = self.search(query, used_by=used_by, limit=limit)
        if not results:
            return "関連メモリは見つかりませんでした。"
        return "\n".join(f"- {record.id}: {record.text}" for record in results)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9_\-]+", text)]
