"""
themes.py — OPTIONAL: title theme clustering vs performance
===========================================================
Groups video titles into themes and reports which themes pull the most real
public views. Kept deliberately lightweight: a pure-numpy TF-IDF + cosine
k-means, so there's no external embeddings dependency to run the demo.

If you want true semantic embeddings, set VOYAGE_API_KEY and swap `_tfidf` for
a call to an embeddings endpoint — the clustering below is model-agnostic.
Operates on REAL public data only (titles + view counts); adds no synthetic
numbers.
"""
from __future__ import annotations

import re

import numpy as np

_STOP = set("the a an of to is in on for and or with this that it my your you i we "
            "why what how new best worst ever now again still vs".split())


def _tokens(t):
    return [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in _STOP and len(w) > 2]


def _tfidf(titles):
    docs = [_tokens(t) for t in titles]
    vocab = sorted({w for d in docs for w in d})
    idx = {w: i for i, w in enumerate(vocab)}
    if not vocab:
        return np.zeros((len(titles), 1)), []
    tf = np.zeros((len(docs), len(vocab)))
    for r, d in enumerate(docs):
        for w in d:
            tf[r, idx[w]] += 1
    df = (tf > 0).sum(axis=0)
    idf = np.log((1 + len(docs)) / (1 + df)) + 1
    m = tf * idf
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms), vocab


def _kmeans(X, k, iters=50, seed=42):
    rng = np.random.default_rng(seed)
    if X.shape[0] <= k:
        return np.arange(X.shape[0])
    centers = X[rng.choice(X.shape[0], k, replace=False)]
    labels = np.zeros(X.shape[0], dtype=int)
    for _ in range(iters):
        sims = X @ centers.T
        new = sims.argmax(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for c in range(k):
            pts = X[labels == c]
            if len(pts):
                centers[c] = pts.mean(axis=0)
    return labels


def cluster_themes(public_videos, k=4) -> dict:
    titles = [v["title"] for v in public_videos]
    views = np.array([v.get("view_count") or 0 for v in public_videos], dtype=float)
    if len(titles) < 4:
        return {"themes": [], "note": "too few videos to cluster"}
    X, vocab = _tfidf(titles)
    k = min(k, len(titles))
    labels = _kmeans(X, k)
    themes = []
    for c in range(k):
        mask = labels == c
        if not mask.any():
            continue
        sub = X[mask].mean(axis=0)
        top_terms = [vocab[i] for i in np.argsort(sub)[::-1][:4]] if len(vocab) else []
        themes.append({
            "theme_terms": top_terms,
            "n_videos": int(mask.sum()),
            "avg_views": int(views[mask].mean()),
            "example_title": titles[int(np.argmax(mask * views))],
        })
    themes.sort(key=lambda t: t["avg_views"], reverse=True)
    return {"themes": themes,
            "note": "Lightweight TF-IDF k-means over REAL public titles/views. "
                    "Set VOYAGE_API_KEY to use semantic embeddings instead."}
