from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


ROOT = Path(
    "/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/data/step_1_raw_scraping_data"
)


DOWNLOADS = [
    {
        "dest": "athleta/athleta_all_styles.xlsx",
        "kind": "sheet_xlsx",
        "id": "1qSyuUTyGi9srPk-gHRG4gRZNqqR6t6yi",
    },
    {
        "dest": "athleta/athleta_all_styles.csv",
        "kind": "drive_file",
        "id": "1ODy0Jm24M__orcuSOoj9BHOoyoRbU6zE",
    },
    {
        "dest": "athleta/athleta_bottoms_top15_clean.xlsx",
        "kind": "sheet_xlsx",
        "id": "1nW_oJd_mcfOmywCwiPsMVyLIhZJWz14u",
    },
    {
        "dest": "athleta/athleta_bottoms_top15_clean.csv",
        "kind": "drive_file",
        "id": "1Cd5c5IkU0MEm2i_5UA7BWRNCXDKYh9RT",
    },
    {
        "dest": "athleta/athleta_bottoms_top15.xlsx",
        "kind": "sheet_xlsx",
        "id": "1XW1eW9iv_aA2tpNiQZypU5PuP9wBgddw",
    },
    {
        "dest": "athleta/athleta_bottoms_top15.csv",
        "kind": "drive_file",
        "id": "1U6GpcN1wbMDG5fFpJ35ymr9GkNc70-ze",
    },
    {
        "dest": "athleta/athleta_prod_links.xlsx",
        "kind": "sheet_xlsx",
        "id": "1xDIRGUl2pXSp9e3RcbmWoZdr1bvLEgCxlD7h9hrns3Y",
    },
    {
        "dest": "babyboo/Babyboo.xlsx",
        "kind": "sheet_xlsx",
        "id": "1xNr75pOloEhmHo2l813v0_1-TIKHK44DevGmCZcR-Is",
    },
    {
        "dest": "bloomchic/BloomChic.xlsx",
        "kind": "sheet_xlsx",
        "id": "1Cckqug8bmehPa4lFPErRfWdCzFC0JVs06oUCtOSTxLE",
    },
    {
        "dest": "bloomchic/bloomchic_reviews_matching_amazon_schema.csv",
        "kind": "drive_file",
        "id": "1lDhwyiiVItnQKLp7sKv7eM4SDhLQag4x",
    },
    {
        "dest": "bloomchic/bloomchic_reviews_matching_amazon_schema_summary.json",
        "kind": "drive_file",
        "id": "1NXqntC5OSoF-7i9Ll7U-fKINUy24jx99",
    },
    {
        "dest": "bloomingdales_aqua/Bloomingdales_Aqua.xlsx",
        "kind": "sheet_xlsx",
        "id": "1YZjuEBfLSBzY-H-uu0yW8JzjJOu8qJUpO_hPf-9_EQs",
    },
    {
        "dest": "chicwish/ChicWish_ProdLinks.xlsx",
        "kind": "sheet_xlsx",
        "id": "14k396O7Rxf23UwQUiwEg6mWOiZ5TiGtGo8Br1T9148o",
    },
    {
        "dest": "chicwish/ChicWish_bigImages_24March2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "1z4x-JgV6RLbw24qM0bCzOkV-GdRmzACNBo2eQIAEf84",
    },
    {
        "dest": "chicwish/ChicWish_bigImages_12March2026_3.csv",
        "kind": "drive_file",
        "id": "1rIDZ4Y-JKkcr3jlRxr1EY1LcoUesEVxY",
    },
    {
        "dest": "cider/Cider.xlsx",
        "kind": "sheet_xlsx",
        "id": "1CcAEHhGNPlHBUAS_43aEl9MSWK1oQ0nfiF1-HdktMaQ",
    },
    {
        "dest": "commense/Commense_Cleaned.xlsx",
        "kind": "sheet_xlsx",
        "id": "1ndw5YbFMJdCRnb0G8idipbZg5E6VxURsbewhVZCXp0c",
    },
    {
        "dest": "cupshe/Cupshe.xlsx",
        "kind": "sheet_xlsx",
        "id": "1sieGVRwpylidVlSjy6U-hV0gHj_gRGMdSc2I6N-KStI",
    },
    {
        "dest": "fehaute/Fehaute.xlsx",
        "kind": "sheet_xlsx",
        "id": "11E3Wm-x3sHUC76-Gb4Tvr4sSEaIlqp5fZuaqjZQsPvg",
    },
    {
        "dest": "gap/Gap_prodLinks.xlsx",
        "kind": "sheet_xlsx",
        "id": "1baaJObS9F44s00m3R7d3D-YaSa6To83z9i5QJ-c8h5U",
    },
    {
        "dest": "halara/Halara.xlsx",
        "kind": "sheet_xlsx",
        "id": "1S3MeLPbsQAt-3LNNUPmqy1xKrHBAFEF5nNwi6o3g9iQ",
    },
    {
        "dest": "harper_wilde/harper_wilde_reviews_matching_amazon_schema.xlsx",
        "kind": "sheet_xlsx",
        "id": "1W2tZflX8iBZdMyE3bgFH9QcwTgPd-gn89HhTNUYcNWg",
    },
    {
        "dest": "harper_wilde/harper_wilde_reviews_matching_amazon_schema.csv",
        "kind": "drive_file",
        "id": "1xZn5qNR6H30uZdLExsnbjAFLYZHMi4CS",
    },
    {
        "dest": "harper_wilde/harper_wilde_reviews_matching_amazon_schema_summary.json",
        "kind": "drive_file",
        "id": "1LDcRzseq2Ic5Gol2_wJR7ksvGV5xBCPg",
    },
    {
        "dest": "llbean/LLBean.xlsx",
        "kind": "sheet_xlsx",
        "id": "1ENQTkWX8kOs75n9DOVtm1QOlHI3vj--rKq8Wt0bMjkQ",
    },
    {
        "dest": "lulus/Lulus_ProdLinks_March2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "1zFPv878A8XRIuEezgnSWozF56398JDxa8VjM9cjScTc",
    },
    {
        "dest": "miss_me_jeans/Miss_Me_Jeans_2April2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "1ctCPRRUREmCkwsKe7lowZJfuKFAJOi3aiQhiriXxd_o",
    },
    {
        "dest": "nuuly/Nuuly.xlsx",
        "kind": "sheet_xlsx",
        "id": "1NJLWleRyRfwHe0WyXEMd2hKj4qp3Z4gEtZm-CcQXDOw",
    },
    {
        "dest": "oglmove/OGL_bigImages_ImageMismatch.xlsx",
        "kind": "sheet_xlsx",
        "id": "1BwvLltJjKtQDwE87O-RpsfZO_DTD2r3yjMuIqh9gfKw",
    },
    {
        "dest": "oglmove/OGL_prodLinks_15March2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "12Xj6R220Wz-OSW3QARrMzyo-Pb_A45g9ImYtklL5XgY",
    },
    {
        "dest": "oglmove/OGL_prodLinks_pants_15March2026.csv",
        "kind": "drive_file",
        "id": "16Nh0zM2aWXk_XVL9SfCVCS2ngfeopFv5",
    },
    {
        "dest": "pinklilly_and_others/PinkLilly_and_others.xlsx",
        "kind": "sheet_xlsx",
        "id": "1WaNN30BXdfQZjF4p16xVHOpHlvgDpvMGYWwRUrcdFF8",
    },
    {
        "dest": "quince/Quince_prodURLs.xlsx",
        "kind": "sheet_xlsx",
        "id": "1xNZ33L48VxoJ56588DqXIHUfZElx24YFVGuNtDjKJes",
    },
    {
        "dest": "rei/rei_activator_pants_reviews.xlsx",
        "kind": "sheet_xlsx",
        "id": "1FkWJ5jAXBHJ92jy3nZdMDYgSMxB-4oPi",
    },
    {
        "dest": "rei/rei_activator_pants_reviews_clean.xlsx",
        "kind": "sheet_xlsx",
        "id": "1769OsU5FB86NNqykTefHxVUx9wjPq6gH",
    },
    {
        "dest": "rei/rei_all_products_reviews.xlsx",
        "kind": "sheet_xlsx",
        "id": "1NVgJBnr3UPSGJ2-F1BS6s0oC_tsIkmAr",
    },
    {
        "dest": "rei/rei_sitewide_smoke.xlsx",
        "kind": "sheet_xlsx",
        "id": "1gn15P2jViJ0rAQHVR35lQGo9_ULn6Dkn",
    },
    {
        "dest": "rent_the_runway/All_RTR_Pro_Links.xlsx",
        "kind": "sheet_xlsx",
        "id": "1cv5jfxJTYlaRbw6asD0VSCkvRNx-ntuEVsggx6Om3p0",
    },
    {
        "dest": "rent_the_runway/RTR.xlsx",
        "kind": "sheet_xlsx",
        "id": "11TyT6BOg1k553OMR4JgIzRuXt1zCon9SILxrGnH2-T8",
    },
    {
        "dest": "rent_the_runway/ReviewExtract_RTR_25Feb2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "1LK-mVfMAmEmhIfNsvjqV-q5Oz9rDAFn93JSlRvRnmOY",
    },
    {
        "dest": "rent_the_runway/RTR_GetBigImages_3April2026.csv",
        "kind": "drive_file",
        "id": "1v9VIWsoOn1gUYPSOdSYqGv07n2nBJssN",
    },
    {
        "dest": "rent_the_runway/RTR_GetBigImages_3April2026_1.csv",
        "kind": "drive_file",
        "id": "1x-m4SVMC19iSiN7hoYVpMUD3F7M9XWlq",
    },
    {
        "dest": "rent_the_runway/RTR_GetBigImages_10April2026_1.csv",
        "kind": "drive_file",
        "id": "1_2mWKPOiEoF6WCZGGDg04jXfByQzD_d0",
    },
    {
        "dest": "shapermint/shapermint_reviews_matching_amazon_schema.xlsx",
        "kind": "sheet_xlsx",
        "id": "1YvmLZ6wKWuxOMzDubc3GPHo2jVuVfNUMs_R4FPywlCA",
    },
    {
        "dest": "shapermint/shapermint_reviews_matching_amazon_schema_summary.json",
        "kind": "drive_file",
        "id": "1RMlkLdQsRdhh2nFFMuiyVp3-hk066TSf",
    },
    {
        "dest": "shein/Shein_bigImages_17March2026.xlsx",
        "kind": "sheet_xlsx",
        "id": "1sxg10L2IMZOb1pbPff5b76JbVi9qCs4hCSm5Bk71sVY",
    },
    {
        "dest": "shein/us.csv",
        "kind": "drive_file",
        "id": "1wUf7Wq2UhZ8rdEHChAr9wBrIIXXp_LkI",
    },
    {
        "dest": "soma/soma_reviews_matching_amazon_schema.xlsx",
        "kind": "sheet_xlsx",
        "id": "1icKEGEMwlbNXLJenQjdXHfJgRhJ0e0VKF8VqVhiR0Nk",
    },
    {
        "dest": "soma/soma_reviews_matching_amazon_schema.csv",
        "kind": "drive_file",
        "id": "1F4MPJlQYwY9qTyC6W3xIhODw_WD-cibt",
    },
    {
        "dest": "soma/soma_reviews_matching_amazon_schema_summary.json",
        "kind": "drive_file",
        "id": "15ei6hjOOOW-nq0vqe4j7XCfTkVhJ2VWy",
    },
    {
        "dest": "ta3swim/TA3Swim.xlsx",
        "kind": "sheet_xlsx",
        "id": "1lswGHZF_XTKsSpr2kwcKHXAASEONbRm2WBPynaxbi94",
    },
    {
        "dest": "universal_standard/universalstandard_full_filtered_deduped_v2.xlsx",
        "kind": "sheet_xlsx",
        "id": "1Rzzzk8uBlE2F-AwevBd24d-jN7wOdrTo",
    },
    {
        "dest": "universal_standard/universalstandard_full_filtered_deduped_v2.csv",
        "kind": "drive_file",
        "id": "1h8Jak81_NlKJOtfOu_rU6EheRtupkdUp",
    },
    {
        "dest": "universal_standard/archive/universalstandard_full_filtered.xlsx",
        "kind": "sheet_xlsx",
        "id": "1oilxKVMC-bT5SzQmrKAOG0bIfUQvIfIV",
    },
    {
        "dest": "universal_standard/archive/universalstandard_full_filtered.csv",
        "kind": "drive_file",
        "id": "1mxRxOyHxM9gc3BhSTnvCObB3SpbRhJZi",
    },
    {
        "dest": "urban_outfitters/UO_BigImages.xlsx",
        "kind": "sheet_xlsx",
        "id": "1OAu16JDgoOrO6T68xEGZwtGDc93vZ9LMfyPcOBcUHzY",
    },
    {
        "dest": "vs/VS.xlsx",
        "kind": "sheet_xlsx",
        "id": "1I8Y9bEEOKSby6IKmAisNte5QFb_LN54ChL88LZK2e9k",
    },
    {
        "dest": "wrangler/Wrangler.xlsx",
        "kind": "sheet_xlsx",
        "id": "1Yb_9OsLKuphyyJVcX8ruSRtL9zXs7W71swc4i81PyNA",
    },
    {
        "dest": "zaful/Zaful_no_Size_ordered_info.xlsx",
        "kind": "sheet_xlsx",
        "id": "1Op-i45v6m1fFhY_Z4dpoLwR598CzPmcjkKaBX0LQF2g",
    },
]


def build_url(item: dict[str, str]) -> str:
    if item["kind"] == "sheet_xlsx":
        return f"https://docs.google.com/spreadsheets/d/{item['id']}/export?format=xlsx"
    return f"https://drive.google.com/uc?export=download&id={item['id']}"


def load_cookie_jar() -> CookieJar:
    import browser_cookie3  # type: ignore

    cookie_file = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
    return browser_cookie3.chrome(cookie_file=str(cookie_file))


def download(url: str, cookie_jar: CookieJar) -> bytes:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    with opener.open(url, timeout=120) as response:
        return response.read()


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    cookie_jar = load_cookie_jar()
    results: list[dict[str, str | int]] = []
    filters = [re.compile(pattern) for pattern in sys.argv[1:]]

    for item in DOWNLOADS:
        dest = ROOT / item["dest"]
        rel_dest = str(dest.relative_to(ROOT))
        if filters and not any(pattern.search(rel_dest) for pattern in filters):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            results.append({"dest": rel_dest, "status": "skipped_existing"})
            print(f"SKIP {rel_dest}", flush=True)
            continue
        url = build_url(item)
        try:
            data = download(url, cookie_jar)
            dest.write_bytes(data)
            results.append(
                {
                    "dest": rel_dest,
                    "status": "ok",
                    "bytes": len(data),
                    "url": url,
                }
            )
            print(f"OK  {rel_dest}  {len(data)} bytes", flush=True)
        except urllib.error.HTTPError as exc:
            results.append(
                {
                    "dest": rel_dest,
                    "status": "http_error",
                    "code": exc.code,
                    "url": url,
                }
            )
            print(f"ERR {rel_dest}  HTTP {exc.code}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "dest": rel_dest,
                    "status": "error",
                    "error": repr(exc),
                    "url": url,
                }
            )
            print(f"ERR {rel_dest}  {exc!r}", file=sys.stderr, flush=True)

    log_path = ROOT / "_drive_download_log.json"
    log_path.write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
