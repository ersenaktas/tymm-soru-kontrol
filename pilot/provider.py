from __future__ import annotations
from pathlib import Path
from typing import Callable, Protocol
import asyncio, hashlib, os, subprocess, sys

from .review_contract import canonicalize_report_markdown, missing_detailed_sections, report_detail_score

class NotebookProvider(Protocol):
    async def login(self, browser: str = "chrome", force: bool = False) -> None: ...
    async def review(self, prompt: str, question_file: Path, subject: str, subject_file: Path | None = None, on_progress: Callable[[str, str], None] | None = None, *, question_title: str | None = None, delivery_instruction: str | None = None, report_mode: str = "full") -> str: ...
    async def disconnect(self, clear_auth: bool = False) -> None: ...

class FakeNotebookProvider:
    def __init__(self): self.logged_in = False; self.calls: list[str] = []
    async def login(self, browser: str = "chrome", force: bool = False) -> None:
        self.logged_in = True; self.calls.append("login:" + browser)
    async def review(self, prompt: str, question_file: Path, subject: str, subject_file: Path | None = None, on_progress=None, *, question_title: str | None = None, delivery_instruction: str | None = None, report_mode: str = "full") -> str:
        if not self.logged_in: raise RuntimeError("Sahte sağlayıcı bağlı değil")
        self.calls.append("review:" + (question_title or question_file.name))
        if on_progress:
            for key, text in (("notebook_create", "Geçici defter oluşturuluyor"), ("rules_upload", "Kontrol yönergesi ekleniyor"), ("subject_upload", "Ders kaynağı ekleniyor"), ("question_upload", "Soru dosyası ekleniyor"), ("analysis", "Sahte sağlayıcı değerlendirmeyi oluşturuyor"), ("cleanup", "Geçici defter temizleniyor")):
                on_progress(key, text)
        return (
            "# TYMM SORU KONTROL RAPORU\n\n"
            f"**Ders / Sınıf:** {subject} / İncelenemedi\n"
            "**Öğrenme Çıktısı:** İncelenemedi\n"
            "**Süreç Bileşeni / Beceri Kodu:** İncelenemedi\n"
            "**Kapsanan Sorular:** Soru 1\n"
            "**Genel Sonuç:** ⚪ Sınırlı İnceleme\n\n"
            "## A — TYMM UYGUNLUĞU\n\n"
            "### Genel TYMM Değerlendirmesi\n\n"
            "#### A.1.15 — Sorular, öğrenme kanıtları ve program uygulama çerçevesiyle uyumlu mu?\n\n"
            "Kapsam: Genel — Soru 1\n"
            "Sonuç: ⚪ İncelenemedi\n"
            "Sınırlılık: Sahte sağlayıcı gerçek ders ve soru içeriğini değerlendirmez.\n"
            "Gerekli Bilgi: Gerçek NotebookLM değerlendirmesi gerekir.\n\n"
            "## B — BAĞLAM\n\n"
            "Raporlanacak sorun bulunmadı.\n\n"
            "## C — SORU BAZLI DEĞERLENDİRME\n\n"
            "### Soru 1\n\n"
            "Raporlanacak sorun bulunmadı.\n\n"
            "## D — SET DÜZEYİ DEĞERLENDİRME\n\n"
            "Tek soru bulunduğu için set düzeyi değerlendirme uygulanamaz."
        )
    async def disconnect(self, clear_auth: bool = False) -> None:
        self.logged_in = False; self.calls.append("disconnect")

class NotebookLMPyProvider:
    """Real adapter. Browser login is delegated to notebooklm-py's CLI.

    When *notebooklm_home* is given every notebooklm CLI call runs with
    ``NOTEBOOKLM_HOME`` set to that directory, which isolates each teacher's
    Playwright browser profile and auth state from all other users.
    """
    UPLOAD_TIMEOUT_SECONDS = 300.0
    CHAT_TIMEOUT_SECONDS = 600.0
    QUESTION_SOURCE_PREFIX = "[SoruKontrol]"
    MAX_DETAIL_RECOVERY_MODULES = 8

    def __init__(self, notebooklm_home: Path | None = None):
        self.client = None; self._context = None
        self._notebooklm_home = notebooklm_home

    def _env(self) -> dict:
        """Return os.environ patched with the per-user NOTEBOOKLM_HOME if set."""
        env = os.environ.copy()
        if self._notebooklm_home:
            self._notebooklm_home.mkdir(parents=True, exist_ok=True)
            env["NOTEBOOKLM_HOME"] = str(self._notebooklm_home)
        return env

    async def login(self, browser: str = "chrome", force: bool = False) -> None:
        # A local cookie-file check alone can pass after NotebookLM has
        # invalidated the session server-side.  The passive token check is
        # read-only and catches that state before a review is started.
        if not force:
            try:
                local_check = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "notebooklm", "--quiet", "auth", "check"],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=45,
                    env=self._env(),
                )
            except (OSError, subprocess.TimeoutExpired):
                local_check = None
            local_output = f"{getattr(local_check, 'stdout', '')}\n{getattr(local_check, 'stderr', '')}"
            if local_check is not None and local_check.returncode == 0 and "Authentication is valid" in local_output:
                try:
                    token_check = await asyncio.to_thread(
                        subprocess.run,
                        [sys.executable, "-m", "notebooklm", "--quiet", "auth", "check", "--test", "--passive"],
                        check=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=45,
                        env=self._env(),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    token_check = None
                if token_check is not None and token_check.returncode == 0:
                    return

        if force:
            # Remove an expired NotebookLM session before interactive login.
            # The browser profile itself is retained so a previously selected
            # Google account can still be offered by the login window.
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "notebooklm", "auth", "logout"],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=45,
                    env=self._env(),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

        command = [sys.executable, "-m", "notebooklm", "login"]
        if browser == "firefox": command += ["--browser-cookies", "firefox"]
        else: command += ["--browser", browser, "--browser-timeout", "600"]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=660,
                env=self._env(),
            )
            # Fallback: if 'chrome' channel fails due to missing binary, try 'chromium'
            if completed.returncode != 0 and browser == "chrome" and "Chromium distribution 'chrome' is not found" in (completed.stderr or completed.stdout or ""):
                alt_command = [sys.executable, "-m", "notebooklm", "login", "--browser", "chromium", "--browser-timeout", "600"]
                completed = await asyncio.to_thread(
                    subprocess.run,
                    alt_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=660,
                    env=self._env(),
                )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Gmail girişi 10 dakika içinde tamamlanmadı. Tarayıcıdaki giriş penceresini tamamlayıp yeniden deneyin.") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            detail = self._redact_login_output(detail)
            suffix = f" Ayrıntı: {detail[-900:]}" if detail else " notebooklm auth check komutunu çalıştırın."
            raise RuntimeError("Gmail girişi başarısız oldu." + suffix)
        # Do not create the API client here: the web handler and the job engine
        # use different asyncio.run loops. The client is loop-affine.

    def import_storage_state(self, raw_json: str | bytes) -> bool:
        """Save a storage_state.json payload directly into this session's profile."""
        import json as _json
        if isinstance(raw_json, bytes):
            raw_json = raw_json.decode("utf-8", errors="replace")
        try:
            data = _json.loads(raw_json)
            if not isinstance(data, dict):
                raise ValueError("JSON bir nesne (object) olmalıdır.")
        except Exception as exc:
            raise ValueError(f"Geçersiz JSON formatı: {exc}") from exc

        # Save to notebooklm home profile directory
        target_dir = (self._notebooklm_home or Path.home() / ".notebooklm") / "profiles" / "default"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "storage_state.json"
        target_file.write_text(_json.dumps(data, indent=2), encoding="utf-8")

        # Also save at root of notebooklm_home for legacy lookup
        if self._notebooklm_home:
            (self._notebooklm_home / "storage_state.json").write_text(_json.dumps(data, indent=2), encoding="utf-8")

        return True

    @staticmethod
    def _redact_login_output(value: str) -> str:
        """Keep CLI diagnostics useful without exposing cookie values."""
        import re

        text = re.sub(r"(?i)(SID|PSID|cookie(?: value)?|token)\s*[=:]\s*[^\s,;]+", r"\1=[gizli]", value)
        text = re.sub(r"(?i)[A-Za-z]:\\[^\r\n]*storage_state\.json", "NotebookLM oturum dosyası", text)
        return " ".join(text.split())

    async def _open_client(self):

        try:
            from notebooklm import NotebookLMClient
        except ImportError as exc:
            raise RuntimeError("notebooklm-py kurulu değil; pip install -e .[notebooklm]") from exc
        kwargs = {}
        if self._notebooklm_home:
            kwargs["storage_path"] = str(self._notebooklm_home)
        self._context = NotebookLMClient.from_storage(**kwargs)
        self.client = await self._context.__aenter__()


    async def review(self, prompt: str, question_file: Path, subject: str, subject_file: Path | None = None, on_progress=None, *, question_title: str | None = None, delivery_instruction: str | None = None, report_mode: str = "full") -> str:
        try:
            from notebooklm import NotebookLMClient
        except ImportError as exc:
            raise RuntimeError("notebooklm-py kurulu değil; pip install -e .[notebooklm]") from exc
        if subject_file is None:
            raise ValueError("V7 değerlendirme akışı için ilgili ders .md kaynağı zorunludur.")
        if not delivery_instruction:
            raise ValueError("V7 teslim istemi paketi bulunamadı; azaltılmış değerlendirme çalıştırılmadı.")

        # The client is created and closed inside the same asyncio loop as the job.
        # Timeouts match the established project's 300s upload / 600s chat setup.
        client_kwargs: dict = {
            "timeout": self.UPLOAD_TIMEOUT_SECONDS,
            "chat_timeout": self.CHAT_TIMEOUT_SECONDS,
        }
        if self._notebooklm_home:
            client_kwargs["storage_path"] = str(self._notebooklm_home)
        async with NotebookLMClient.from_storage(**client_kwargs) as client:
            notebook = None
            try:

                self._progress(on_progress, "notebook_create", "Geçici NotebookLM defteri oluşturuluyor")
                notebook = await self._retry(lambda: client.notebooks.create(f"Soru kontrol {question_file.stem}"))
                self._progress(on_progress, "rules_upload", "Kontrol yönergesi güvenli olarak ekleniyor")
                rule_source = await self._retry(lambda: client.sources.add_text(
                    notebook.id,
                    "soru_kontrol_V7.md",
                    prompt,
                    wait=True,
                    wait_timeout=self.UPLOAD_TIMEOUT_SECONDS,
                ))
                scoped_sources = [rule_source]
                subject_source_title = subject_file.name
                self._progress(on_progress, "subject_upload", f"Ders kaynağı ekleniyor: {subject_source_title}")
                scoped_sources.append(await self._retry(lambda: client.sources.add_file(
                    notebook.id,
                    subject_file,
                    wait=True,
                    wait_timeout=self.UPLOAD_TIMEOUT_SECONDS,
                    title=subject_source_title,
                )))
                display_name = question_title or question_file.name
                question_source_title = self._question_source_title(question_file, display_name)
                self._progress(on_progress, "question_upload", f"Soru dosyası ekleniyor: {display_name}")
                scoped_sources.append(await self._retry(lambda: client.sources.add_file(
                    notebook.id,
                    question_file,
                    wait=True,
                    wait_timeout=self.UPLOAD_TIMEOUT_SECONDS,
                    title=question_source_title,
                )))
                source_ids = [source.id for source in scoped_sources]
                await self._enable_detailed_mode(client, notebook.id, on_progress)
                # V7 performs the full internal review but reports only
                # actionable and unreviewable findings in its fixed format.
                chat_prompt = self._render_delivery_instruction(
                    delivery_instruction,
                    display_name,
                    subject_source_title,
                    report_mode=report_mode,
                )
                self._progress(on_progress, "analysis", "Soru, güncel V7 ölçütleri ve ilgili ders kaynağıyla değerlendiriliyor")
                answer = await self._retry_chat(
                    lambda: client.chat.ask(notebook.id, chat_prompt, source_ids=source_ids),
                    on_progress,
                    "analysis",
                    attempts=5,
                )
                answer_text = self._answer_text(answer)
                return await self._recover_report_detail(
                    client,
                    notebook.id,
                    source_ids,
                    answer_text,
                    on_progress,
                )
            finally:
                if notebook is not None:
                    self._progress(on_progress, "cleanup", "Geçici defter ve kaynaklar siliniyor")
                    await client.notebooks.delete(notebook.id)
                    self._progress(on_progress, "cleanup", "Geçici defter ve kaynaklar temizlendi")

    @staticmethod
    def _progress(callback, key: str, text: str) -> None:
        if callback: callback(key, text)

    @staticmethod
    def _answer_text(answer: object) -> str:
        return str(getattr(answer, "answer", getattr(answer, "text", answer)))

    async def _enable_detailed_mode(self, client, notebook_id: str, callback) -> None:
        """Prefer NotebookLM's built-in longer response mode for this temp job.

        The setting is stored only on the notebook currently being processed;
        the notebook is deleted in ``finally``.  It is intentionally best
        effort, because the packaged V7 delivery instruction remains the
        authoritative instruction if a future notebooklm-py version lacks the
        setting endpoint.
        """
        set_mode = getattr(getattr(client, "chat", None), "set_mode", None)
        if not callable(set_mode):
            return
        try:
            from notebooklm import ChatMode

            self._progress(callback, "detail_mode", "Ayrıntılı NotebookLM yanıt modu etkinleştiriliyor")
            await self._retry(lambda: set_mode(notebook_id, ChatMode.DETAILED))
            self._progress(callback, "detail_mode", "Ayrıntılı NotebookLM yanıt modu etkin")
        except Exception:
            # Do not fail a teacher's review merely because this optional API
            # setting is unavailable.  No prompt or session content is logged.
            self._progress(callback, "detail_mode", "Ayrıntılı mod ayarlanamadı; V7 istemiyle devam ediliyor")

    async def _recover_report_detail(
        self,
        client,
        notebook_id: str,
        source_ids: list[str],
        primary_answer: str,
        callback,
    ) -> str:
        """Repair V7 content/format in scoped passes and keep the richest report."""
        primary_answer = canonicalize_report_markdown(primary_answer)
        primary_missing = missing_detailed_sections(primary_answer)
        self._progress(
            callback,
            "detail_recovery",
            "V7 rapor yapısı bağımsız bir ikinci geçişle doğrulanıyor"
            if not primary_missing
            else "Eksik V7 rapor yapısı bağımsız bir ikinci geçişle tamamlanıyor",
        )
        repair_prompt = (
            "Bu bağımsız bir ikinci kalite kontrolüdür. İlk yanıtın kararlarını ve "
            "biçimini doğru varsayma. Yalnız seçili soru dosyası, ilgili ders kaynağı "
            "ve soru_kontrol_V7.md kaynağını kullanarak bütün uygulanabilir ölçütleri "
            "yeniden kontrol et. Raporu V7'nin ÇIKTI KURALLARI ve RAPOR ŞABLONU ile "
            "baştan sona eksiksiz üret. İlk satır `# TYMM SORU KONTROL RAPORU` olsun; "
            "A, B, C ve D bölümleri doğru sırada yer alsın; A'da Genel TYMM "
            "Değerlendirmesi bulunsun ve C'de dosyadaki her soru ayrı `### Soru N` "
            "başlığıyla gösterilsin. Rapora yalnız ❌ Uygun Değil, ⚠️ Düzeltilmeli "
            "ve ⚪ İncelenemedi bulgularını al; ✅ Uygun ve ⚪ Uygulanamaz ölçütleri "
            "yazma. Üst bilgideki beş alanın her birini tek satırda yaz; birden çok "
            "soruya ait süreç/beceri kodlarını aynı Süreç Bileşeni / Beceri Kodu "
            "satırında `Soru 1: ...; Soru 2: ...` biçiminde göster. Markdown tablosu "
            "kullanma; kaynak tablosundan kanıt gerekiyorsa hücreleri düz metinle "
            "okuma sırasına göre aktar. Yalnız rapor Markdown'ını döndür ve D bölümünden sonra hiçbir "
            "kapanış veya açıklama ekleme."
        )
        try:
            reply = await self._retry_chat(
                lambda: client.chat.ask(notebook_id, repair_prompt, source_ids=source_ids),
                callback,
                "detail_recovery",
                attempts=3,
            )
        except Exception:
            self._progress(callback, "detail_recovery", "V7 ikinci denetimi tamamlanamadı; ilk yanıt korunuyor")
            return primary_answer
        candidate = canonicalize_report_markdown(self._answer_text(reply))
        best = max((primary_answer, candidate), key=report_detail_score)
        remaining = missing_detailed_sections(best)
        if remaining:
            self._progress(callback, "detail_recovery", "Kalan V7 biçim eksikleri son bir geçişle düzeltiliyor")
            gap_list = "; ".join(remaining[:12])
            format_prompt = (
                "En son ürettiğiniz V7 raporunu yeniden verin. Kararları, bulguları, "
                "kanıtları ve revizyon önerilerini değiştirmeyin; yalnızca Markdown "
                "yapısını V7 RAPOR ŞABLONU ile birebir uyumlu hâle getirin. Her alanı "
                "ayrı satırda yazın; alan satırlarının başına madde imi koymayın. "
                "Beş üst bilgi alanını tek satırlı tutun; süreç/beceri kodlarını ayrı "
                "maddelere bölmeyin ve Markdown tablosu kullanmayın. "
                "C bölümünde dosyadaki her soruyu ayrı `### Soru N` başlığı altında "
                "koruyun. Biçim denetiminde kalan eksikler: " + gap_list + ". "
                "Yalnız tam rapor Markdown'ını döndürün; açıklama veya kapanış eklemeyin."
            )
            try:
                final_reply = await self._retry_chat(
                    lambda: client.chat.ask(notebook_id, format_prompt, source_ids=source_ids),
                    callback,
                    "detail_recovery",
                    attempts=3,
                )
                final_candidate = canonicalize_report_markdown(self._answer_text(final_reply))
                best = max((best, final_candidate), key=report_detail_score)
            except Exception:
                self._progress(callback, "detail_recovery", "Son V7 biçim geçişi tamamlanamadı; en eksiksiz yanıt korundu")

        if not missing_detailed_sections(best):
            self._progress(callback, "detail_recovery", "V7 rapor yapısı doğrulandı")
        else:
            self._progress(callback, "detail_recovery", "V7 yapısı tamamlanamadı; en eksiksiz NotebookLM yanıtı korunuyor")
        return best

    @staticmethod
    def _render_delivery_instruction(template: str, filename: str, subject_source: str, *, report_mode: str = "full") -> str:
        """Render the binding V7 delivery prompt for every output mode.

        ``report_mode`` remains in the public signature for provider
        compatibility, but it must never influence NotebookLM's analysis.
        V7 itself controls which statuses may be visible in the report.
        """
        if "{filename}" not in template or "{subject_source}" not in template:
            raise ValueError("V7 teslim istemi şablonu doğrulanamadı.")
        try:
            rendered = template.format(filename=filename, subject_source=subject_source)
        except (KeyError, ValueError):
            raise ValueError("V7 teslim istemi şablonu doğrulanamadı.") from None
        return rendered

    @classmethod
    def _question_source_title(cls, path: Path, display_name: str) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"{cls.QUESTION_SOURCE_PREFIX}:{digest.hexdigest()[:12]} {display_name}"

    @staticmethod
    async def _retry(operation, attempts: int = 3):
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    raise
                await asyncio.sleep(attempt * 3)
        raise last_error  # pragma: no cover

    @staticmethod
    def _is_auth_error(error: Exception) -> bool:
        normalized = " ".join(str(error).casefold().split())
        return any(marker in normalized for marker in (
            "authentication expired",
            "authentication invalid",
            "_loginredirecterror",
            "accounts.google.com",
            "run 'notebooklm login'",
        ))

    @staticmethod
    def _is_transient_chat_error(error: Exception) -> bool:
        normalized = " ".join(str(error).casefold().split())
        return isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError)) or any(
            marker in normalized
            for marker in (
                "no parseable chunks",
                "streaming chat response",
                "response was empty",
                "empty response",
                "akış kodu 11",
                "akis kodu 11",
                "stream code 11",
                "temporarily",
                "temporary",
                "timeout",
                "timed out",
                "connection reset",
                "rate limit",
                "resource exhausted",
                "429",
                "502",
                "503",
                "504",
            )
        )

    async def _retry_chat(self, operation, callback, progress_key: str, *, attempts: int = 5):
        """Retry only transient NotebookLM stream failures in one notebook.

        Empty/chunk-parse replies are common transient failures of the private
        streaming endpoint.  Retrying the same scoped chat avoids opening a
        second notebook and preserves the source isolation guarantee.  Login
        failures are surfaced immediately so the teacher can reconnect.
        """
        delays = (4, 8, 15, 25)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                answer = await operation()
                if not self._answer_text(answer).strip():
                    raise RuntimeError("NotebookLM response was empty")
                return answer
            except Exception as exc:
                last_error = exc
                if self._is_auth_error(exc) or not self._is_transient_chat_error(exc):
                    raise
                if attempt == attempts:
                    raise RuntimeError(
                        "NotebookLM yanıt akışı geçici olarak tamamlanamadı. "
                        f"Aynı geçici defterde {attempts} güvenli deneme yapıldı; "
                        "birkaç dakika sonra yeniden deneyin."
                    ) from exc
                self._progress(
                    callback,
                    progress_key,
                    f"NotebookLM yanıt akışı geçici olarak kesildi; aynı defterde yeniden deneniyor ({attempt + 1}/{attempts})",
                )
                await asyncio.sleep(delays[min(attempt - 1, len(delays) - 1)])
        raise last_error  # pragma: no cover

    async def disconnect(self, clear_auth: bool = False) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None; self.client = None
        if clear_auth:
            await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "notebooklm", "auth", "logout"], check=False, capture_output=True, text=True)
