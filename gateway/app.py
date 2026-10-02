import asyncio
import json
import os
import secrets
import time
import re
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "true").lower() in {"1", "true", "yes"}
TOKEN = os.environ.get("API_TOKEN", "")
BRIDGE = os.environ.get("BRIDGE_URL", "http://127.0.0.1:18181")
REPO = os.environ.get("REPOSITORY_URL", "https://raw.githubusercontent.com/fixered/zeroTituli/master/repo.json")
REPOS = list(dict.fromkeys(url.strip() for url in os.environ.get("REPOSITORY_URLS", REPO).split(",") if url.strip()))
if not REPOS:
    raise RuntimeError("Configurare almeno un repository")
repository_lock = asyncio.Lock()
DATA = Path(os.environ.get("DATA_DIR", "/data"))
client: httpx.AsyncClient
bootstrap = {"state": "starting"}

@dataclass
class Media:
    url: str
    headers: dict
    expires: float
    template: str | None = None

media: dict[str, Media] = {}
TEMPLATE = re.compile(r"\$[A-Za-z]+(?:%0[0-9]+d)?\$")

def register(url: str, headers: dict) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "URL media non supportato")
    now = time.monotonic()
    for key in list(media):
        if media[key].expires <= now:
            del media[key]
    for key, item in media.items():
        if item.url == url and item.headers == headers:
            item.expires = now + 3600
            return "/media/" + key + "/resource"
    if len(media) >= 4000:
        raise HTTPException(503, "Limite sessioni media raggiunto")
    key = secrets.token_urlsafe(24)
    media[key] = Media(url, dict(headers), now + 3600)
    return "/media/" + key + "/resource"

def register_template(url: str, headers: dict) -> str:
    tokens = TEMPLATE.findall(url)
    route = register(url, headers).rsplit("/", 1)[0]
    pattern = "t-" + "~".join(tokens)
    media[route.rsplit("/", 1)[1]].template = pattern
    return route + "/" + pattern

bearer = HTTPBearer(auto_error=False)

async def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not AUTH_REQUIRED:
        return
    if credentials is None or not secrets.compare_digest(credentials.credentials, TOKEN):
        raise HTTPException(401, "Token API richiesto")

async def rpc(method: str, route: str, payload=None):
    try:
        response = await client.request(method, BRIDGE + route, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Runtime Android non disponibile") from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Risposta Android non valida") from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code, result.get("error", "Errore provider"))
    return result

async def import_repositories():
    global bootstrap
    async with repository_lock:
        bootstrap = {"state": "starting"}
        results = []
        for url in REPOS:
            try:
                result = await rpc("POST", "/repository", {"url": url})
                result["url"] = url
                results.append(result)
            except Exception as exc:
                results.append({"url": url, "error": str(exc), "plugins": []})
        good = all(not r.get("error") and r.get("plugins") and all(p.get("loaded") for p in r["plugins"]) for r in results)
        any_loaded = any(p.get("loaded") for r in results for p in r.get("plugins", []))
        bootstrap = {"state": "ready" if good else "partial" if any_loaded else "error", "result": {"repositories": results}}
        return bootstrap["result"]

async def initialise():
    await asyncio.sleep(3)
    await import_repositories()

@asynccontextmanager
async def lifespan(app):
    global client
    if AUTH_REQUIRED and not TOKEN:
        raise RuntimeError("API_TOKEN deve essere configurato")
    DATA.mkdir(parents=True, exist_ok=True)
    client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), trust_env=False)
    task = asyncio.create_task(initialise())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await client.aclose()

app = FastAPI(title="CloudStream Docker API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(Path(__file__).parent / "static/index.html")

@app.get("/config", include_in_schema=False)
async def config():
    return {"authRequired": AUTH_REQUIRED}

@app.get("/health")
async def health():
    return {"service": "running", "repository": bootstrap["state"]}

@app.get("/api/status", dependencies=[Depends(auth)])
async def status():
    return {"bootstrap": bootstrap, "android": await rpc("GET", "/health")}

def repository_hash(url):
    value = 0
    for char in url:
        value = (31 * value + ord(char)) & 0xffffffff
    return value if value < 0x80000000 else value - 0x100000000

async def provider_list():
    items = await rpc("GET", "/providers")
    repositories = bootstrap.get("result", {}).get("repositories", [])
    for item in items:
        source = item.get("sourcePlugin", "")
        for repo in repositories:
            if "." + str(repository_hash(repo["url"])) + "/" in source:
                item["repository"] = repo.get("repository", repo["url"])
                break
        item["displayName"] = item["name"] + (" · " + item["repository"] if item.get("repository") else "")
    return items

@app.get("/api/providers", dependencies=[Depends(auth)])
async def providers():
    return await provider_list()

@app.post("/api/repository", dependencies=[Depends(auth)])
async def repository(payload: dict):
    if "url" in payload and payload["url"] not in REPOS:
        raise HTTPException(422, "Configurare REPOSITORY_URLS per aggiungere repository")
    return await import_repositories()

@app.post("/api/provider/{operation}", dependencies=[Depends(auth)])
async def provider(operation: str, payload: dict):
    if operation not in {"home", "search", "load", "resolve"}:
        raise HTTPException(404, "Operazione sconosciuta")
    if not isinstance(payload.get("provider"), str):
        raise HTTPException(422, "Specificare provider")
    required = {"search": "query", "load": "url", "resolve": "data"}.get(operation)
    if required and not isinstance(payload.get(required), str):
        raise HTTPException(422, "Specificare " + required)
    if operation in {"home", "search"}:
        if type(payload.get("page", 1)) is not int or payload.get("page", 1) < 1:
            raise HTTPException(422, "page deve essere >= 1")
    result = await rpc("POST", "/provider/" + operation, payload)
    if operation == "resolve":
        for stream in result.get("streams", []):
            stream["playbackUrl"] = register(stream["url"], stream.get("headers") or {})
    return result

def hls_rewrite(text: str, base: str, headers: dict) -> str:
    def attribute(match):
        return 'URI="' + register(urljoin(base, match[1]), headers) + '"'
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            line = re.sub(r'URI="([^"]+)"', attribute, line)
        elif line.strip():
            line = register(urljoin(base, line.strip()), headers)
        lines.append(line)
    return "\n".join(lines) + "\n"

def dash_rewrite(text: str, base: str, headers: dict) -> str:
    # BaseURL inheritance is resolved before templates are rewritten. Templates keep
    # $Number$, $Time$, $RepresentationID$ and their formatting for the browser.
    ET.register_namespace("", "urn:mpeg:dash:schema:mpd:2011")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.fromstring(text)
    ns = "{urn:mpeg:dash:schema:mpd:2011}"
    def visit(node, parent_base):
        bases = node.findall(ns + "BaseURL")
        effective = urljoin(parent_base, bases[0].text or "") if bases else parent_base
        for child in bases:
            child.text = register(urljoin(parent_base, child.text or ""), headers).rsplit("/", 1)[0] + "/"
        for attr in ("media", "initialization", "sourceURL", "href"):
            if attr in node.attrib:
                absolute = urljoin(effective, node.attrib[attr])
                if TEMPLATE.search(absolute):
                    node.attrib[attr] = register_template(absolute, headers)
                else:
                    node.attrib[attr] = register(absolute, headers)
        for child in node:
            if child.tag != ns + "BaseURL": visit(child, effective)
    visit(root, base)
    return ET.tostring(root, encoding="unicode")

@app.get("/media/{key}/{path:path}", include_in_schema=False)
async def relay(key: str, path: str, request: Request):
    item = media.get(key)
    if item is None or item.expires < time.monotonic():
        raise HTTPException(410, "Sessione scaduta: risolvere nuovamente lo stream")
    item.expires = time.monotonic() + 3600
    target = item.url
    if item.template:
        # Substitute DASH placeholders without splitting signed query strings or
        # allowing the browser to change the registered origin/base URL.
        regex = re.escape(item.template)
        for token in TEMPLATE.findall(item.template):
            regex = regex.replace(re.escape(token), r"([A-Za-z0-9_.=-]+)", 1)
        match = re.fullmatch(regex, path)
        if match is None: raise HTTPException(400, "Template media non valido")
        for token, value in zip(TEMPLATE.findall(target), match.groups()):
            target = target.replace(token, value, 1)
        target = target.replace("$$", "$")
    elif path != "resource":
        # DASH template requests are restricted to the registered base directory.
        if not re.fullmatch(r"[A-Za-z0-9_./%~+@=!*(),;'-]+", path) or ".." in path or path.startswith("/"):
            raise HTTPException(400, "Percorso media non valido")
        target = urljoin(target, path)
        if request.url.query:
            target += "?" + request.url.query
    headers = dict(item.headers)
    if "range" in request.headers: headers["Range"] = request.headers["range"]
    response = None
    for _ in range(6):
        call = client.build_request("POST", BRIDGE + "/media", json={"url": target, "headers": headers})
        try: response = await client.send(call, stream=True)
        except httpx.HTTPError as exc: raise HTTPException(502, "Media non raggiungibile") from exc
        if response.status_code not in {301, 302, 303, 307, 308}: break
        redirect = urljoin(target, response.headers.get("location", ""))
        await response.aclose()
        if urlsplit(redirect).scheme not in {"http", "https"}: raise HTTPException(502, "Redirect non valido")
        # Don't forward session credentials to a different origin.
        if urlsplit(redirect).netloc != urlsplit(target).netloc:
            headers = {k:v for k,v in headers.items() if k.lower() not in {"authorization","cookie"}}
        target = redirect
    else: raise HTTPException(502, "Troppi redirect")
    content_type = response.headers.get("content-type", "application/octet-stream")
    playlist = "mpegurl" in content_type.lower() or urlsplit(target).path.lower().endswith(".m3u8")
    dash = "dash+xml" in content_type.lower() or urlsplit(target).path.lower().endswith(".mpd")
    if response.is_success and (playlist or dash):
        chunks = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 4 * 1024 * 1024: raise HTTPException(502, "Manifest troppo grande")
            text = chunks.decode("utf-8-sig")
            rewritten = hls_rewrite(text, target, headers) if playlist else dash_rewrite(text, target, headers)
            return Response(rewritten, media_type="application/vnd.apple.mpegurl" if playlist else "application/dash+xml")
        finally: await response.aclose()
    async def chunks():
        try:
            async for chunk in response.aiter_bytes(): yield chunk
        finally: await response.aclose()
    passed = {k: response.headers[k] for k in ["content-length","content-range","accept-ranges"] if k in response.headers}
    passed["Cache-Control"] = "no-store"
    return StreamingResponse(chunks(), status_code=response.status_code, media_type=content_type, headers=passed)
