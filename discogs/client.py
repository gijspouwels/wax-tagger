"""
Discogs API wrapper met OAuth 1.0a authenticatie.

Eerste keer: opent browser voor autorisatie, slaat access token op.
Daarna: laadt opgeslagen token automatisch.
"""

import os
import re
import time
import json
import webbrowser
import requests
import discogs_client
from typing import Optional

from models import Release as DiscogsRelease
import config


class DiscogsClient:
    def __init__(self):
        self._client = self._authenticate()
        os.makedirs(config.ARTWORK_TMP_DIR, exist_ok=True)
        self._last_request_time = 0.0
        self._release_cache: dict[int, Optional["DiscogsRelease"]] = {}

    # ─── Authenticatie ─────────────────────────────────────────────────────────

    def _authenticate(self) -> discogs_client.Client:
        """
        Authenticeer via OAuth 1.0a.
        Laadt opgeslagen tokens als die er zijn, anders start de OAuth-flow.
        """
        if os.path.exists(config.OAUTH_TOKEN_FILE):
            return self._load_saved_tokens()

        return self._run_oauth_flow()

    def _make_client(self, token: Optional[str] = None, secret: Optional[str] = None) -> discogs_client.Client:
        kwargs = dict(
            consumer_key=config.DISCOGS_CONSUMER_KEY,
            consumer_secret=config.DISCOGS_CONSUMER_SECRET,
        )
        if token and secret:
            kwargs["token"] = token
            kwargs["secret"] = secret

        return discogs_client.Client(config.DISCOGS_USER_AGENT, **kwargs)

    def _load_saved_tokens(self) -> discogs_client.Client:
        """Laad opgeslagen access token en herstel de sessie."""
        with open(config.OAUTH_TOKEN_FILE, "r") as f:
            data = json.load(f)

        client = self._make_client(
            token=data["access_token"],
            secret=data["access_token_secret"],
        )

        # Snelle verificatie — alleen bij 401 opnieuw authenticeren
        try:
            client.identity()
        except discogs_client.exceptions.HTTPError as e:
            if "401" in str(e):
                os.remove(config.OAUTH_TOKEN_FILE)
                return self._run_oauth_flow()
            # Andere fouten (netwerk, rate limit) negeren — token is waarschijnlijk geldig
        except Exception:
            pass  # Netwerk- of parse-fout, token behouden

        return client

    def _run_oauth_flow(self) -> discogs_client.Client:
        """
        Voer de OAuth 1.0a-flow uit:
        1. Haal request token op
        2. Open browser voor autorisatie
        3. Gebruiker voert verifier in
        4. Wissel in voor access token en sla op
        """
        client = self._make_client()

        # Stap 1: request token + autorisatie-URL ophalen
        request_token, request_secret, authorize_url = client.get_authorize_url()

        print(f"\nOpen deze URL in je browser om de app te autoriseren:\n{authorize_url}\n")
        webbrowser.open(authorize_url)

        # Stap 2: verifier invoeren (Discogs toont deze na goedkeuring)
        verifier = input("Voer de verifier-code in die Discogs geeft: ").strip()

        # Stap 3: request token in fetcher herstellen en verifier inwisselen
        client._fetcher.store_token(request_token, request_secret)
        access_token, access_token_secret = client.get_access_token(verifier)

        # Stap 4: opslaan voor volgende sessies
        with open(config.OAUTH_TOKEN_FILE, "w") as f:
            json.dump({
                "access_token": access_token,
                "access_token_secret": access_token_secret,
            }, f)
        os.chmod(config.OAUTH_TOKEN_FILE, 0o600)  # alleen eigenaar kan lezen

        print(f"Authenticatie geslaagd! Token opgeslagen in {config.OAUTH_TOKEN_FILE}\n")
        return client

    # ─── Rate limiting ─────────────────────────────────────────────────────────

    def _rate_limit(self):
        """Wacht minimaal 1 seconde tussen requests (Discogs-limiet: 60/min)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.time()

    # ─── Zoeken ────────────────────────────────────────────────────────────────

    # Versie-suffixen die worden gestript voor de fallback-zoekopdracht
    _VERSION_SUFFIX_RE = re.compile(
        r'\s*[\(\[](original mix|extended mix|extended|clean extended|clean|'
        r'radio edit|club mix|instrumental|acapella|dub mix|remix|edit|mix|'
        r'version|vip|remaster|remastered|feat\..*|ft\..*|single version|'
        r'album version)[^\)\]]*[\)\]]\s*$',
        re.IGNORECASE,
    )

    # "feat." / "ft." / "featuring" / "presents" uit artiestsnaam strippen
    _FEAT_RE = re.compile(r'\s*(feat\.?|ft\.?|featuring|presents?)\s+.+$', re.IGNORECASE)

    # Leidend prefix (The / DJ / MC) uit artiestsnaam strippen
    _ARTIST_PREFIX_RE = re.compile(r'^(the|dj|mc)\s+', re.IGNORECASE)

    # Eerste haakjesblok uit een titel ophalen (bijv. "Bart Claessen Remix" uit "(Bart Claessen Remix)")
    _BRACKET_RE = re.compile(r'[\(\[](.*?)[\)\]]')

    # Laatste haakjesblok afkappen (zonder geneste haakjes), ongeacht de inhoud
    # Vangt bijv. "(M&S Extended Vocal)" in "Salsoul Nugget (If U Wanna) (M&S Extended Vocal)"
    _LAST_BRACKET_RE = re.compile(r'\s*[\(\[][^\(\[\)\]]*[\)\]]\s*$')

    def search(self, artist: str, title: str, max_results: int = 5) -> list[DiscogsRelease]:
        """
        Zoek op Discogs via meerdere strategieën (stopt bij de eerste met resultaten).
        Strategieën 1–12: releasetitel + artiest-varianten.
        Strategie 13: editor/mixer-naam uit haakjesblok als artiest (bijv. "Underdog" uit "(Underdog Edit)").
        Fallback: tracktitel-zoekopdracht via track=-parameter, vindt compilaties
                  waar de trackartiest verschilt van de release-artiest.
        """
        base_title  = self._VERSION_SUFFIX_RE.sub('', title).strip()
        norm_artist = re.sub(r'[-_]', ' ', artist).strip()
        no_feat     = self._FEAT_RE.sub('', norm_artist).strip()
        short_title = ' '.join(base_title.split()[:2])

        # Eerste 2 woorden uit het suffix-haakjesblok (bijv. "Bart Claessen" uit "(Bart Claessen Remix)")
        bracket_match = self._BRACKET_RE.search(title)
        bracket_words = ' '.join(bracket_match.group(1).split()[:2]) if bracket_match else ''
        enriched_title = f"{base_title} {bracket_words}".strip() if bracket_words else base_title

        # Laatste haakjesgroep afkappen (ongeacht inhoud) — fallback voor custom remix-namen
        title_no_last = self._LAST_BRACKET_RE.sub('', title).strip()

        # Artiest-varianten: progressief agressiever strippen
        # "Orbital, Penelope Isles" → "Orbital"
        first_artist = re.sub(r'\s*,.*$', '', no_feat).strip()
        # "The Wildchild Experience" → "Wildchild Experience" | "DJ Krust" → "Krust"
        no_prefix    = self._ARTIST_PREFIX_RE.sub('', first_artist).strip()
        # "The Wildchild Experience" → "Wildchild"
        first_word   = no_prefix.split()[0] if no_prefix else ''

        # Editor/mixer-naam uit haakjesblok: "(Underdog Edit)" → "Underdog"
        _GENERIC_BRACKET = re.compile(
            r'^(original|extended|radio|club|dub|vocal|instrumental|acapella|album|single|clean|vip)$',
            re.IGNORECASE,
        )
        bracket_editor = ''
        if bracket_match:
            raw = re.sub(r'\s+(edits?|mixes?|remixes?|re-edits?|reworks?)$', '', bracket_match.group(1), flags=re.I).strip()
            if raw and not _GENERIC_BRACKET.match(raw):
                bracket_editor = raw

        strategies = [
            (title,          artist),       # 1.  origineel
            (base_title,     artist),       # 2.  basis titel
            (base_title,     norm_artist),  # 3.  + genormaliseerde artiest
            (base_title,     no_feat),      # 4.  + zonder feat./presents
            (enriched_title, no_feat),      # 5.  + eerste 2 bracket-woorden (remix-naam)
            (title_no_last,  no_feat),      # 6.  laatste haakjesgroep afgekapt + zonder feat.
            (title_no_last,  norm_artist),  # 7.  laatste haakjesgroep afgekapt + norm. artiest
            (base_title,     first_artist), # 8.  komma-collaborator afgekapt
            (title_no_last,  first_artist), # 9.  laatste bracket + komma-collaborator
            (base_title,     no_prefix),    # 10. The/DJ/MC-prefix gestript
            (base_title,     first_word),   # 11. eerste woord van gestripte artiest
            (short_title,    no_feat),      # 12. eerste 2 woorden + zonder feat.
        ]
        if bracket_editor:
            strategies.append((base_title, bracket_editor))  # 13. editor/mixer als artiest

        seen = set()
        for search_title, search_artist in strategies:
            if (search_title, search_artist) in seen:
                continue
            seen.add((search_title, search_artist))
            results = self._execute_search(search_artist, search_title, max_results)
            if results:
                return results

        return []

    def _execute_search(self, artist: str, title: str, max_results: int) -> list[DiscogsRelease]:
        """Voer één zoekopdracht uit met retry bij lege response."""
        for attempt in range(2):
            try:
                self._rate_limit()
                results = self._client.search(title, artist=artist, type="release")

                releases = []
                seen_masters: set[int] = set()

                for result in results:
                    try:
                        release = self._parse_search_result(result)
                        if release is None:
                            continue
                        dedup_key = release.master_id or release.release_id
                        if dedup_key in seen_masters:
                            continue
                        seen_masters.add(dedup_key)
                        releases.append(release)
                        if len(releases) >= max_results:
                            break
                    except Exception:
                        continue

                return releases

            except Exception:
                if attempt == 0:
                    time.sleep(3)
                else:
                    return []

        return []

    def _parse_search_result(self, result) -> Optional[DiscogsRelease]:
        try:
            release_id = result.id
            title = result.title or ""

            # Discogs-zoekresultaten: "Artiest - Album"
            if " - " in title:
                artist_part, album_part = title.split(" - ", 1)
            else:
                artist_part, album_part = "", title

            year = None
            try:
                year = int(result.year) if result.year else None
            except (ValueError, TypeError):
                pass

            genres = list(result.genres or [])
            styles = list(result.styles or [])

            # Artwork: cover_image heeft hogere resolutie dan thumb
            artwork_url = None
            if hasattr(result, "cover_image") and result.cover_image:
                artwork_url = result.cover_image
            elif hasattr(result, "thumb") and result.thumb:
                artwork_url = result.thumb

            master_id = getattr(result, "master_id", None)

            label = None
            if hasattr(result, "labels") and result.labels:
                label = result.labels[0].name

            fmt = None
            if hasattr(result, "formats") and result.formats:
                fmt = result.formats[0].get("name")

            return DiscogsRelease(
                release_id=str(release_id),
                title=album_part.strip(),
                artist=artist_part.strip(),
                year=year,
                genres=genres,
                styles=styles,
                label=label,
                artwork_url=artwork_url,
                source_url=f"https://www.discogs.com/release/{release_id}",
                master_id=master_id,
                format=fmt,
            )
        except Exception:
            return None

    # ─── Release-details ───────────────────────────────────────────────────────

    def get_earliest_release_id(self, master_id: int, fallback_id: int, current_year: Optional[int]) -> int:
        """
        Geeft het release-ID van de vroegste bekende persing via de master.
        Geeft fallback_id terug als er geen eerdere persing gevonden wordt.
        Scant maximaal één pagina (50 versies) om extra API-calls te beperken.
        """
        try:
            self._rate_limit()
            master = self._client.master(master_id)
            original_year = master.year

            # Huidige release is al vroeg genoeg
            if not original_year or (current_year and original_year >= current_year):
                return fallback_id

            best_id = fallback_id
            best_year = current_year or 9999

            for i, version in enumerate(master.versions):
                if i >= 50:
                    break
                v_year = getattr(version, 'year', None)
                if v_year and v_year < best_year:
                    best_year = v_year
                    best_id = version.id
                if best_year == original_year:
                    break  # vroegst mogelijke jaar gevonden

            return best_id
        except Exception:
            return fallback_id

    def resolve_master(self, master_id: int) -> Optional[int]:
        """Zet een master-ID om naar het hoofd-release-ID."""
        try:
            self._rate_limit()
            master = self._client.master(master_id)
            return master.main_release.id
        except Exception:
            return None

    def get_details_from_pinned(self, url_type: str, id_str: str) -> Optional[DiscogsRelease]:
        """
        Haal release-details op vanuit een gepinde Discogs-URL.
        url_type: "release" of "master"
        id_str:   het numerieke ID als string
        """
        release_id = int(id_str)
        if url_type == "master":
            release_id = self.resolve_master(release_id)
            if not release_id:
                return None
        return self.get_release_details(release_id)

    def get_release_details(self, release_id: "int | str") -> Optional[DiscogsRelease]:
        """
        Haal volledige details op van een release.
        Geeft betere metadata (hogere-res artwork, volledige genres) dan zoekresultaten.
        Bij een lege/foutieve response: één retry na korte pauze, daarna None.
        Resultaten worden gecached voor de duur van de run.
        """
        release_id = int(release_id)
        if release_id in self._release_cache:
            return self._release_cache[release_id]

        for attempt in range(2):
            try:
                self._rate_limit()
                release = self._client.release(release_id)
                _ = release.title  # forceer API-aanroep

                artist = ""
                if release.artists:
                    artist = release.artists[0].name

                year = None
                try:
                    year = int(release.year) if release.year else None
                except (ValueError, TypeError):
                    pass

                genres = list(release.genres or [])
                styles = list(release.styles or [])

                artwork_url = None
                if release.images:
                    primary = next(
                        (img for img in release.images if img.get("type") == "primary"),
                        release.images[0],
                    )
                    artwork_url = primary.get("uri") or primary.get("uri150")

                label = None
                if release.labels:
                    label = release.labels[0].name

                master_id = getattr(release, "master_id", None)

                fmt = None
                if release.formats:
                    fmt = release.formats[0].get("name")

                result = DiscogsRelease(
                    release_id=str(release_id),
                    title=release.title,
                    artist=artist,
                    year=year,
                    genres=genres,
                    styles=styles,
                    label=label,
                    artwork_url=artwork_url,
                    source_url=f"https://www.discogs.com/release/{release_id}",
                    master_id=master_id,
                    format=fmt,
                )
                self._release_cache[release_id] = result
                return result
            except Exception:
                if attempt == 0:
                    time.sleep(3)
                else:
                    self._release_cache[release_id] = None
                    return None

        return None

    # ─── Artwork ───────────────────────────────────────────────────────────────

    def download_artwork(self, release: DiscogsRelease) -> Optional[str]:
        """
        Download artwork naar een tijdelijk bestand.
        Geeft het lokale pad terug, of None bij mislukking.
        """
        if not release.artwork_url:
            return None

        # Controleer of artwork al gecached is op schijf
        for ext in (".jpg", ".png"):
            cached = os.path.join(config.ARTWORK_TMP_DIR, f"release_{release.release_id}{ext}")
            if os.path.exists(cached):
                return cached

        self._rate_limit()
        try:
            # OAuth-headers genereren via de fetcher en dan downloaden met requests
            fetcher = self._client._fetcher
            headers = {"User-Agent": config.DISCOGS_USER_AGENT}
            _, signed_headers, _ = fetcher.client.sign(
                release.artwork_url,
                http_method="GET",
                headers=headers,
            )
            response = requests.get(release.artwork_url, headers=signed_headers, timeout=15)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"

            path = os.path.join(
                config.ARTWORK_TMP_DIR,
                f"release_{release.release_id}{ext}",
            )
            with open(path, "wb") as f:
                f.write(response.content)
            return path
        except Exception:
            return None
