    release = str(p.get("release_date") or "")
    if not has_sample:
        return ""
    return (f"『{title}』は、{talent}を迎えた{maker}のグラビアDVDです。発売日は{release}。"
            "公開されているサンプル映像とサンプル画像を確認できるため、購入前に作品の雰囲気をチェックしやすい作品です。"
            "本ページの紹介文は、公開されている公式商品情報とサンプル情報をもとに自動生成しています。")


def product_page(p):
    title = str(p.get("title") or "グラビアDVD")
    maker = str(p.get("maker") or "")
    talent = "、".join(p.get("talent") or [])
    release = str(p.get("release_date") or "")
    source = str(p.get("source_url") or "")
    buy = str(p.get("affiliate_url") or "")
    cover_remote = str(p.get("cover_image_url") or "")
    cover = local_media(cover_remote) or cover_remote
    # DMM may return a generic placeholder before an upcoming title's jacket is publicly released.
    title_unreleased = title.startswith("タイトル未定")
    if title_unreleased and not sample_images_remote:
        cover = ""
    sample_images_remote = [str(x) for x in (p.get("sample_image_urls") or []) if str(x).startswith(("http://", "https://"))][:12]
    sample_images = [local_media(x) or x for x in sample_images_remote]
    sample_video = str(p.get("sample_video_url") or "")
    has_sample = bool(p.get("sample_available") and sample_video)

    actions = []
    if buy:
        actions.append(f'<a class="buy" href="{esc(buy)}" rel="sponsored nofollow">FANZAで購入する</a>')
    if source:
        actions.append(f'<a class="btn" href="{esc(source)}" rel="nofollow">メーカー公式情報</a>')

    media = ''
    if cover:
        media += f'<img class="cover" src="{esc(cover)}" alt="{esc(title)}" loading="eager">'
    elif title_unreleased:
        media += '<div class="cover cover-placeholder" role="img" aria-label="ジャケット画像未公開"><div>JACKET IMAGE</div><span>ジャケット画像は公開後に表示されます</span></div>'
    if has_sample:
        media += '<div class="sample-video"><h3>サンプル映像</h3>'
        if re.search(r"\.(?:mp4|m3u8)(?:$|[?#])", sample_video, re.I):
            media += f'<video controls playsinline preload="metadata" poster="{esc(cover)}"><source src="{esc(sample_video)}"></video>'
        else:
            media += f'<iframe src="{esc(sample_video)}" title="{esc(title)} サンプル映像" loading="lazy" allowfullscreen referrerpolicy="no-referrer-when-downgrade"></iframe>'
        media += '</div>'
    if has_sample and sample_images:
        media += '<div class="sample-video"><h3>サンプル画像</h3><div class="gallery">'
        media += ''.join(f'<a href="{esc(img)}" target="_blank" rel="noopener"><img src="{esc(img)}" alt="{esc(title)} サンプル画像" loading="lazy"></a>' for img in sample_images)
        media += '</div></div>'

    if has_sample:
        review = f'<section class="box review"><h3>レビュー・見どころ</h3><p>{esc(original_review(p, True))}</p><div class="note">※レビュー本文は他サイトの記事を転載せず、公式商品情報と公開サンプル情報から当サイト向けに自動生成しています。</div></section>'
        body = f'<article><div class="box"><div class="hero"><div>{media or ""}</div><div><span class="badge">サンプル映像あり</span><p class="muted">{esc(maker)} / {esc(release)}</p><h2>{esc(title)}</h2>{f"<p><strong>出演：</strong>{esc(talent)}</p>" if talent else ""}<div class="actions">{"".join(actions) if actions else ""}</div></div></div></div>{review}<p class="back"><a href="/">← 新作一覧へ戻る</a></p></article>'
        return body

    rows = []
    for label, value in (("メーカー", maker), ("出演", talent), ("発売日", release)):
        if value: