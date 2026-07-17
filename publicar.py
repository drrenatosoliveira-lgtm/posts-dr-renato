#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publicar.py — Publicação/agendamento no Instagram via Graph API OFICIAL do Meta.
Grátis. Sem terceiros acessando a conta.

Fluxo Instagram Content Publishing:
  1) cria "container" de mídia (image_url público + legenda)
  2) (carrossel) cria 1 container por imagem + 1 container CAROUSEL com os filhos
  3) publica o container (media_publish)

Requisitos (o usuário configura uma vez — ver referencias/SETUP_PUBLICACAO.md):
  - IG Profissional (Business) ligado a uma Página do Facebook
  - App no Meta for Developers + token de longa duração
  - Imagens hospedadas em URL pública (ex.: GitHub raw)

Config (config.json  ->  seção "publicacao"; token também via env META_TOKEN):
  "publicacao": {
    "access_token": "",
    "base_url": "https://raw.githubusercontent.com/USUARIO/REPO/main",
    "graph_version": "v21.0",
    "contas": { "dr-renato": {"ig_user_id": ""}, "cardiogym": {"ig_user_id": ""}, "paraoka": {"ig_user_id": ""} }
  }

Uso:
  python publicar.py agora  --marca dr-renato --slug 2026-07-22_cerebro-exercicio
  python publicar.py agenda            # publica os itens vencidos de agenda.json (usado pelo cron)
  (sem token -> DRY-RUN: só mostra o que faria)
"""
import argparse, glob, json, os, sys, time
import requests

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass

BASE = os.path.dirname(os.path.abspath(__file__))
GRAPH = "https://graph.facebook.com"


def cfg():
    # estrutura pública (committável): publicacao.json  (base_url, ig ids). SEM token.
    p = os.path.join(BASE, "publicacao.json")
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: pass
    return {}


def token(pub):
    # token NUNCA no repo (token.txt/config.json são gitignorados). Ordem: env -> token.txt -> config.json.
    if os.environ.get("META_TOKEN"):
        return os.environ["META_TOKEN"]
    tt = os.path.join(BASE, "token.txt")
    if os.path.exists(tt):
        t = open(tt, encoding="utf-8").read().strip()
        if len(t) > 50:  # ignora arquivo vazio/placeholder
            return t
    cj = os.path.join(BASE, "config.json")
    if os.path.exists(cj):
        try: return json.load(open(cj, encoding="utf-8")).get("publicacao", {}).get("access_token", "")
        except Exception: pass
    return ""


def upload_publico(local_path):
    # sobe a imagem para um host público (catbox.moe, grátis e sem chave) e devolve a URL.
    with open(local_path, "rb") as f:
        r = requests.post("https://catbox.moe/user/api.php",
                          data={"reqtype": "fileupload"}, files={"fileToUpload": f}, timeout=120)
    u = r.text.strip()
    if r.status_code >= 400 or not u.startswith("http"):
        raise RuntimeError(f"host público falhou: {r.status_code} {u[:120]}")
    return u


def urls_publicas(pub, marca, fotos):
    base = pub.get("base_url", "")
    if base and "USUARIO/REPO" not in base:  # repo próprio configurado
        return [f"{base.rstrip('/')}/{marca}/aprovacao/{f}" for f in fotos]
    out = []  # sem repo -> hospeda na hora
    for f in fotos:
        u = upload_publico(os.path.join(BASE, marca, "aprovacao", f))
        print("   ↑ hospedado:", u)
        out.append(u)
    return out


def imagens(marca, slug):
    """Retorna (lista_de_arquivos_ordenada, tipo). Feed = *_post.png; carrossel = *_hdNN.png."""
    d = os.path.join(BASE, marca, "aprovacao")
    post = os.path.join(d, f"{slug}_post.png")
    if os.path.exists(post):
        return [f"{slug}_post.png"], "feed"
    hd = sorted(glob.glob(os.path.join(d, f"{slug}_hd*.png")))
    return [os.path.basename(x) for x in hd], "carrossel"


def legenda(marca, slug):
    p = os.path.join(BASE, marca, "aprovacao", f"{slug}_caption.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""


def url_imagem(pub, marca, fname):
    base = pub.get("base_url", "").rstrip("/")
    return f"{base}/{marca}/aprovacao/{fname}"


def _post(url, params):
    r = requests.post(url, data=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph API {r.status_code}: {r.text}")
    return r.json()


def _aguarda_container(ig, cid, tok, ver, tentativas=20):
    for _ in range(tentativas):
        r = requests.get(f"{GRAPH}/{ver}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30)
        st = r.json().get("status_code")
        if st == "FINISHED": return
        if st == "ERROR": raise RuntimeError(f"container {cid} deu ERROR")
        time.sleep(3)


def publicar(marca, slug, dry=False):
    pub = cfg(); tok = token(pub); ver = pub.get("graph_version", "v21.0")
    ig = pub.get("contas", {}).get(marca, {}).get("ig_user_id", "")
    fotos, tipo = imagens(marca, slug)
    if not fotos:
        print(f"[erro] sem imagens renderizadas para {slug}"); return False
    cap = legenda(marca, slug)
    if dry or not tok or not ig:
        motivo = "DRY-RUN" if dry else ("sem token (crie token.txt)" if not tok else "sem ig_user_id")
        print(f"🧪 [{motivo}] {marca} · {slug} · {tipo} ({len(fotos)} img)")
        for f in fotos: print("   img local:", f)
        print("   legenda:", (cap[:90] + "…") if len(cap) > 90 else cap)
        return True
    print(f"→ hospedando {len(fotos)} imagem(ns)…")
    urls = urls_publicas(pub, marca, fotos)

    if tipo == "feed":
        cont = _post(f"{GRAPH}/{ver}/{ig}/media", {"image_url": urls[0], "caption": cap, "access_token": tok})["id"]
        _aguarda_container(ig, cont, tok, ver)
    else:  # carrossel
        filhos = []
        for u in urls:
            cid = _post(f"{GRAPH}/{ver}/{ig}/media", {"image_url": u, "is_carousel_item": "true", "access_token": tok})["id"]
            _aguarda_container(ig, cid, tok, ver); filhos.append(cid)
        cont = _post(f"{GRAPH}/{ver}/{ig}/media",
                     {"media_type": "CAROUSEL", "children": ",".join(filhos), "caption": cap, "access_token": tok})["id"]
        _aguarda_container(ig, cont, tok, ver)
    res = _post(f"{GRAPH}/{ver}/{ig}/media_publish", {"creation_id": cont, "access_token": tok})
    print(f"✅ publicado {marca} · {slug} -> id {res.get('id')}")
    return True


def cmd_agora(a):
    publicar(a.marca, a.slug, dry=a.dry)


def cmd_agenda(a):
    """Publica itens vencidos de agenda.json (para o cron do GitHub Actions)."""
    from datetime import datetime
    p = os.path.join(BASE, "agenda.json")
    if not os.path.exists(p):
        print("agenda.json não encontrado"); return
    itens = json.load(open(p, encoding="utf-8"))
    agora = datetime.now().astimezone()
    mudou = False
    for it in itens:
        if it.get("status") != "pendente": continue
        quando = datetime.fromisoformat(it["quando"]).astimezone()
        if quando <= agora:
            print(f"→ publicando {it['slug']} (agendado {it['quando']})")
            ok = publicar(it["marca"], it["slug"], dry=a.dry)
            if ok and not a.dry:
                it["status"] = "publicado"; mudou = True
    if mudou:
        json.dump(itens, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
    pa = s.add_parser("agora"); pa.add_argument("--marca", required=True); pa.add_argument("--slug", required=True)
    pa.add_argument("--dry", action="store_true"); pa.set_defaults(func=cmd_agora)
    pg = s.add_parser("agenda"); pg.add_argument("--dry", action="store_true"); pg.set_defaults(func=cmd_agenda)
    a = p.parse_args(); a.func(a)


if __name__ == "__main__":
    main()
