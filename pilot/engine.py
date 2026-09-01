from __future__ import annotations
import asyncio, hashlib, json, logging, re, unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from .models import ReviewJob, ReviewResult
from .rules import load_delivery_instruction, load_rules
from .exporter import export_report
from .review_contract import canonicalize_report_markdown, complete_blank_source_fields, missing_detailed_sections

log=logging.getLogger("pilot")

ENGINE_BUILD = "0.6.47-larger-header-logo"
CACHE_SCHEMA = 2

class ReviewEngine:
    def __init__(self, provider, rules_path: Path, output_dir: Path):
        self.provider=provider; self.rules_path=rules_path; self.output_dir=output_dir
    async def run(self, job: ReviewJob, on_progress: Callable[[str, str], None] | None = None) -> ReviewResult:
        source_name = job.display_name or job.path.name
        preserved_markdown = ""
        preserved_markdown_path: Path | None = None
        try:
            self._progress(on_progress, "rules", "V7 kural paketi bellekte hazırlanıyor")
            prompt=load_rules(self.rules_path)  # never logged
            delivery_instruction=load_delivery_instruction(self.rules_path.with_name("delivery.bin"))
            if not delivery_instruction:
                raise FileNotFoundError("V7 teslim istemi paketi bulunamadı; azaltılmış değerlendirme çalıştırılmadı.")
            subject=job.subject_label or (job.subject if job.subject != "auto" else "otomatik")
            # V7 has one binding output contract: full internal review,
            # issues/unreviewable findings only in the visible report.
            report_mode = "issues"
            fingerprint, metadata = self._fingerprint(job, source_name, subject, prompt, delivery_instruction, report_mode)
            if not job.force_refresh:
                cached = self._load_cached(job, source_name, fingerprint)
                if cached is not None:
                    self._progress(on_progress, "cache_hit", "Aynı girdinin doğrulanmış raporu kullanılıyor")
                    return cached
            self._progress(on_progress, "notebook", "NotebookLM bağlantısı açılıyor")
            full_markdown=await self.provider.review(
                prompt,
                job.path,
                subject,
                job.subject_path,
                on_progress=on_progress,
                question_title=source_name,
                delivery_instruction=delivery_instruction,
                report_mode=report_mode,
            )
            full_markdown=canonicalize_report_markdown(self._clean_answer(full_markdown))
            # Missing source information is represented by an empty Word/PDF
            # field. No value is invented, and structural/report decisions
            # remain mandatory.
            full_markdown=complete_blank_source_fields(full_markdown)
            preserved_markdown=full_markdown
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stem=self._report_stem(job.path, source_name)
            markdown_path=self.output_dir/(stem+".md")
            # Preserve NotebookLM's completed work before structural validation
            # or Word/PDF conversion. A failed export is therefore recoverable.
            markdown_path.write_text(full_markdown+"\n", encoding="utf-8", newline="\n")
            preserved_markdown_path=markdown_path
            missing_sections=missing_detailed_sections(full_markdown)
            if missing_sections:
                self._progress(on_progress, "detail_recovery", "V7 biçimi tamamlanamadı; NotebookLM yanıtı kaydedildi")
                detail="; ".join(missing_sections[:8])
                raise RuntimeError(
                    "NotebookLM V7 raporunu eksiksiz oluşturamadı "
                    f"({len(missing_sections)} yapısal eksik: {detail}). Word/PDF "
                    "üretilmedi; NotebookLM yanıtı Markdown olarak korundu."
                )
            metadata["analysis_report_mode"] = "v7_full_internal_review"
            metadata["full_report_contract"] = "v7_complete"
            metadata["visible_statuses"] = ["Uygun Değil", "Düzeltilmeli", "İncelenemedi"]
            metadata["omitted_statuses"] = ["Uygun", "Uygulanamaz"]
            metadata["output_transform"] = "format_only_markdown_canonicalization"
            markdown=full_markdown
            self._progress(on_progress, "export", "V7 raporu kurumsal Word ve PDF biçiminde hazırlanıyor")
            json_path=self.output_dir/(stem+".json")
            docx,pdf=export_report(markdown, stem, self.output_dir)
            metadata["cached"] = False
            payload={
                "schema_version": CACHE_SCHEMA,
                "file": source_name,
                "subject": subject,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "answer": markdown,
                "review_metadata": metadata,
            }
            self._write_json(json_path, payload)
            result = ReviewResult(job.id, source_name, markdown, docx, pdf, markdown_path, json_path, metadata=metadata)
            self._save_cache(result, metadata)
            return result
        except Exception as exc:
            log.error("İş başarısız: job_id=%s", job.id)
            return ReviewResult(
                job.id,
                source_name,
                preserved_markdown,
                markdown_path=preserved_markdown_path,
                error=f"{type(exc).__name__}: {exc}",
            )

    def run_many(self, jobs): return asyncio.run(self._run_many(jobs))
    async def _run_many(self, jobs):
        results=[]
        for job in jobs: results.append(await self.run(job))
        return results

    def _report_stem(self, path: Path, display_name: str | None = None) -> str:
        base=Path(display_name).stem.strip() if display_name else path.stem.strip()
        # Preserve Turkish characters, but make teacher-provided titles safe on
        # Windows before using them as report filenames.
        base=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', base).strip(' .-') or "rapor"
        base=base[:140]
        candidate=f"{base}-rapor"; index=2
        while any((self.output_dir/(candidate+suffix)).exists() for suffix in (".docx", ".pdf", ".md", ".json")):
            candidate=f"{base}-rapor ({index})"; index+=1
        return candidate

    @staticmethod
    def _sha256_path(path: Path | None) -> str:
        if path is None or not path.is_file():
            return "missing"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _fingerprint(
        self,
        job: ReviewJob,
        source_name: str,
        subject: str,
        prompt: str,
        delivery_instruction: str,
        report_mode: str = "full",
    ) -> tuple[str, dict]:
        question_hash = self._sha256_path(job.path)
        subject_hash = self._sha256_path(job.subject_path)
        rules_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        delivery_hash = hashlib.sha256(delivery_instruction.encode("utf-8")).hexdigest()
        parts = (
            ENGINE_BUILD,
            source_name,
            subject,
            getattr(job.subject_path, "name", ""),
            question_hash,
            subject_hash,
            rules_hash,
            delivery_hash,
            report_mode,
        )
        fingerprint = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
        metadata = {
            "engine_build": ENGINE_BUILD,
            "cache_schema": CACHE_SCHEMA,
            "fingerprint": fingerprint,
            "question_sha256": question_hash,
            "subject_sha256": subject_hash,
            "rules_sha256": rules_hash,
            "delivery_sha256": delivery_hash,
            "report_mode": report_mode,
            "subject_source": getattr(job.subject_path, "name", ""),
            "isolation_mode": "temporary_notebook_per_job",
            "conversation_policy": "new_temporary_notebook_for_each_job; scoped_sources_only",
        }
        return fingerprint, metadata

    def _cache_manifest(self, fingerprint: str) -> Path:
        return self.output_dir / ".cache" / f"{fingerprint}.json"

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)

    def _load_cached(self, job: ReviewJob, source_name: str, fingerprint: str) -> ReviewResult | None:
        manifest_path = self._cache_manifest(fingerprint)
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != CACHE_SCHEMA or manifest.get("fingerprint") != fingerprint:
                return None
            files = manifest.get("report_files") or {}
            output_root = self.output_dir.resolve()
            resolved: dict[str, Path] = {}
            for key in ("md", "docx", "pdf", "json"):
                name = Path(str(files.get(key, ""))).name
                target = (self.output_dir / name).resolve()
                if not name or target.parent != output_root or not target.is_file():
                    return None
                resolved[key] = target
            answer = resolved["md"].read_text(encoding="utf-8")
            metadata = dict(manifest.get("review_metadata") or {})
            metadata.update({"cached": True, "fingerprint": fingerprint})
            return ReviewResult(
                job.id,
                source_name,
                answer.rstrip("\n"),
                resolved["docx"],
                resolved["pdf"],
                resolved["md"],
                resolved["json"],
                metadata=metadata,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _save_cache(self, result: ReviewResult, metadata: dict) -> None:
        if not result.markdown_path or not result.docx_path or not result.pdf_path or not result.json_path:
            return
        manifest = {
            "schema_version": CACHE_SCHEMA,
            "fingerprint": metadata["fingerprint"],
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "report_files": {
                "md": result.markdown_path.name,
                "docx": result.docx_path.name,
                "pdf": result.pdf_path.name,
                "json": result.json_path.name,
            },
            "review_metadata": metadata,
        }
        self._write_json(self._cache_manifest(metadata["fingerprint"]), manifest)

    @staticmethod
    def _progress(callback: Callable[[str, str], None] | None, key: str, text: str) -> None:
        if callback: callback(key, text)

    @staticmethod
    def _clean_answer(value: str) -> str:
        # Kept equivalent to the established project so report text is cleaned
        # in exactly the same way before validation and export.
        text=value.strip()
        criterion_name_repairs={
            "Süreç bileşeni og bilişsel görev uyumu": "Süreç bileşeni ve bilişsel görev uyumu",
            "Kodların doğruluğu og tutarlılığı": "Kodların doğruluğu ve tutarlılığı",
            "Veri miktarı og veri ayıklama": "Veri miktarı ve veri ayıklama",
        }
        for malformed, correct in criterion_name_repairs.items():
            text=text.replace(malformed, correct)

        def normalize_text(block: str) -> str:
            value=block.casefold().translate(str.maketrans("çğıöşü", "cgiosu"))
            return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))

        def is_offer(block: str) -> bool:
            normalized=normalize_text(block)
            return any(marker in normalized for marker in (
                "ister misiniz", "isterseniz", "hazirlayabilirim", "duzenleyebilirim",
                "olusturabilirim", "yardimci olabilirim", "devam edebilirim",
            ))

        ruled_blocks=re.split(r"\n\s*---\s*\n", text)
        if len(ruled_blocks)>1 and is_offer(ruled_blocks[-1]):
            return "\n---\n".join(ruled_blocks[:-1]).rstrip()
        paragraphs=re.split(r"\n{2,}", text)
        if len(paragraphs)>1 and is_offer(paragraphs[-1]):
            return "\n\n".join(paragraphs[:-1]).rstrip()
        return text

    @staticmethod
    def _normalized(value: str) -> str:
        value=value.casefold().translate(str.maketrans("çğıöşü", "cgiosu"))
        return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))

    @classmethod
    def _has_issue_status(cls, value: str) -> bool:
        normalized=cls._normalized(value)
        return (
            "❌" in value
            or "⚠" in value
            or "uygun degil" in normalized
            or "duzeltilmeli" in normalized
        )

    @classmethod
    def _without_non_evaluated_rows(cls, markdown: str) -> str:
        """Compatibility shim: V7 already controls visible result statuses.

        In particular, ``İncelenemedi`` must remain visible in V7.  Older
        callers may still invoke this method, so it deliberately returns the
        validated Markdown unchanged.
        """
        return markdown
        lines=markdown.splitlines()
        criterion_re=re.compile(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:kriter\s+)?(?:\d+\.\d+|set-\d+)\s*[—-]",
            re.I,
        )
        heading_re=re.compile(r"^\s*#{1,6}\s+")

        def is_non_evaluated(value: str) -> bool:
            normalized=cls._normalized(value)
            return any(label in normalized for label in (
                "uygulanamaz", "incelenemedi", "sinirli inceleme", "inceleme yapilmadi",
            ))

        def is_summary_or_metadata(line: str) -> bool:
            normalized=cls._normalized(line)
            return any(label in normalized for label in (
                "genel sonuc:", "soru sonucu:", "bolum sonucu:",
                "ortak tymm / set sonucu:", "baglam sonucu:",
                "set genel sonucu:", "sb / beceri kodu:",
            ))

        output: list[str]=[]
        index=0
        while index < len(lines):
            line=lines[index]
            if criterion_re.match(line):
                end=index+1
                while end < len(lines):
                    if (
                        criterion_re.match(lines[end])
                        or heading_re.match(lines[end])
                        or lines[end].strip() == "---"
                        or is_summary_or_metadata(lines[end])
                    ):
                        break
                    end+=1
                if not is_non_evaluated(line):
                    output.extend(lines[index:end])
                index=end
                continue
            if is_summary_or_metadata(line) and is_non_evaluated(line):
                index+=1
                continue
            output.append(line)
            index+=1
        return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()

    @classmethod
    def _issues_only_report(cls, markdown: str, source_name: str, subject: str) -> str:
        """Compatibility shim for the single V7 visible-report contract.

        The V7 delivery instruction already omits suitable and inapplicable
        criteria, therefore no second local report shape is generated.
        """
        return markdown
        lines=markdown.splitlines()
        criterion_re=re.compile(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:kriter\s+)?(?:\d+\.\d+|set-\d+)\s*[—-]",
            re.I,
        )
        section_re=re.compile(r"^\s*#{4,6}\s+")
        unit_re=re.compile(r"^\s*#{1,3}\s+")

        header=[
            "### KISA UYGUNSUZLUK RAPORU",
            "",
            f"**Dosya:** {source_name}",
            f"**Ders:** {subject}",
            "**Rapor Türü:** Yalnızca uygun olmayan ve düzeltilmesi gereken maddeler",
        ]
        findings: list[str]=[]
        problem_summaries: list[tuple[str, str]]=[]
        current_unit="### GENEL BULGULAR"
        current_unit_id=0
        current_results: list[str]=[]
        current_section=""
        emitted_unit_id: int | None=None
        emitted_section=""
        issue_count=0
        index=0

        def is_result_line(line: str) -> bool:
            normalized=cls._normalized(line)
            return any(label in normalized for label in (
                "genel sonuc:", "soru sonucu:", "ortak tymm / set sonucu:",
                "baglam sonucu:", "set genel sonucu:",
            ))

        while index < len(lines):
            line=lines[index]
            stripped=line.strip()
            if section_re.match(line):
                current_section=stripped
                index+=1
                continue
            if unit_re.match(line):
                normalized_heading=cls._normalized(stripped)
                if "kisa uygunsuzluk raporu" not in normalized_heading and "kisa rapor" not in normalized_heading:
                    current_unit=stripped
                    current_unit_id+=1
                    current_results=[]
                    current_section=""
                index+=1
                continue
            if is_result_line(line):
                current_results.append(stripped)
                if cls._has_issue_status(line):
                    problem_summaries.append((current_unit, stripped))
                index+=1
                continue
            if not criterion_re.match(line):
                index+=1
                continue

            end=index+1
            while end < len(lines):
                candidate=lines[end]
                if (
                    criterion_re.match(candidate)
                    or section_re.match(candidate)
                    or unit_re.match(candidate)
                    or candidate.strip() == "---"
                    or is_result_line(candidate)
                ):
                    break
                end+=1
            block=lines[index:end]
            block_text="\n".join(block).strip()
            if cls._has_issue_status(block_text):
                if emitted_unit_id != current_unit_id:
                    if findings:
                        findings.extend(["", "---", ""])
                    findings.append(current_unit)
                    if current_results:
                        findings.extend(["", *current_results])
                    emitted_unit_id=current_unit_id
                    emitted_section=""
                if current_section and current_section != emitted_section:
                    findings.extend(["", current_section])
                    emitted_section=current_section
                findings.extend(["", block_text])
                issue_count+=1
            index=end

        if issue_count:
            return "\n".join([*header, "", *findings]).strip()

        if problem_summaries:
            seen: set[tuple[str, str]]=set()
            summary_lines: list[str]=[]
            for unit, result in problem_summaries:
                key=(unit, result)
                if key in seen:
                    continue
                seen.add(key)
                if summary_lines:
                    summary_lines.extend(["", "---", ""])
                summary_lines.extend([unit, "", result])
            return "\n".join([*header, "", *summary_lines]).strip()

        return "\n".join([
            *header,
            "",
            "Bu incelemede uygun olmayan veya düzeltilmesi gereken madde tespit edilmedi.",
        ]).strip()
