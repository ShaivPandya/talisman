# Final export validation (LON-38)

## README revision — October 8, 2026

The canonical ZIP was rebuilt after the full validation recorded below to replace
its README with a product description, concise setup instructions and a walkthrough.
Internal issue references and parent-project context were removed from the README.

- Current ZIP SHA-256: `9123cec3824399a7dda1a63808c456c08ac7df8eb6d214a7914169bce6b15bfc`.
- Current ZIP bytes: 43793509; files: 526.
- The standard export builder and its isolation guard passed. The checksum sidecar matches.
- A comparison of all archive entries found only `longaeva/README.md` changed; every other file's contents and all executable permissions are identical to the fully tested archive below.
- All archive contents match the source package. All 10 local README documentation links resolve.
- The retained standalone repository matches all 526 files and permissions, remains on `hackathon`, has no remotes and is clean after documentation commit `c63da43e514718f6ba2e38fb27c741c1deeed39a`. Its original neutral initial commit is preserved.
- Runtime tests and browser checks were not repeated for this documentation-only revision. The results below refer to the original checksum and the unchanged application code and data.

## Acceptance summary

Final scripted validation and the subsequent browser walkthrough passed against the exact ZIP below. No application APIs, schemas, model inputs or saved forecast artifacts were changed for LON-38.

- Backend: 551 tests passed; ruff, formatting and mypy passed (205 source files).
- Frontend: lint and production build passed; 43 tests passed in the frontend-only image. Its one data-dependent guide test was initially skipped because the image has no package data. The exported data was then mounted read-only and all eight tour tests passed, including that assertion; no test remains unexercised for this reason.
- Inventory: all 191 bundled data files matched the per-file license inventory and SHA-256 checksums. The strict isolation guard reported zero findings. The archive contains 526 files, no Git metadata, no local environment file, no dependency directories and no actual developer home paths. Public source text/provenance and the documented licensing limitations remain intact.
- Startup: two historical origins, seven saved runs, 40 retrospective and 20 prospective forecast rows; repeated seeding preserved a newly recorded review. The report is current, with 16 scored origins and two exclusions.
- Replay: all three fresh 5,000-path/four-quarter paired runs matched exactly before and after restart. All seven bundled runs were numerically equivalent, with maximum relative difference 2.1094237467877974e-15 (below the documented 1e-9 tolerance); their stored outputs and hashes were not rewritten. Both additional CLI/API smoke runs also matched exactly; run A matched again after restart.
- Provider configuration was cleared for the entire verification stack. No new provider call, source collection, calibration, evaluation capture or prospective registration was performed.

- Started (UTC): 2026-10-08T19:05:40Z
- Finished (UTC): 2026-10-08T19:15:25Z
- Result: **PASS**
- Final mode: 1; tests skipped: 0; provider credentials cleared
- ZIP: `longaeva-submission.zip`
- SHA-256: `3287b405a958f9b1b371c16737c1038aef7ea6cee3e7e16a45074b377e90b263`
- ZIP bytes: 43800999
- Docker: `24.0.2`
- Compose: `2.18.1`
- Host: `Darwin 25.5.0 arm64`
- Compose project: `longaeva-verify-9ed102`
- Ports: API=18000 WEB=13000 DB=15432
- Work dir: `/tmp/longaeva-verify.61aiBi`
- Keep: yes (stack and temp dir left in place)

## Steps

| Step | Result | Seconds | Evidence |
| --- | --- | ---: | --- |
| preflight | PASS | 1 | tools, ports 18000/13000/15432, sha256 match |
| unpack | PASS | 1 | 526 entries under longaeva/; exec bits present |
| guard | PASS | 114 | isolation guard --strict: 0 findings |
| git-init | PASS | 3 | fresh git init; 526 files tracked |
| tests | PASS | 368 | make check (ruff, mypy, pytest, frontend) |
| startup | PASS | 33 | make up; api/worker/web/db healthy |
| smoke | PASS | 2 | API /health /openapi.json /runs; web / /runs /api/health |
| final-demo | PASS | 13 | inventory, report, seed/reseed, evidence, evaluation, valuation, paired worker runs and replay |
| scenario | PASS | 8 | run A 3e6e1267-7fa7-4c07-9e04-54dc52762ae6 worker; run B 6829c9e2-9b02-41af-a00e-9cbd8c274149 POST; 68 result rows |
| replay | PASS | 36 | A and B exact_match, llm unset; A exact_match after restart |
| final-replay-after-restart | PASS | 6 | all bundled runs plus fresh paired runs replay after restart |
| clean-tree | PASS | 0 | git status --porcelain empty |

## Excerpts


### make check

```
docker compose build --no-cache
#1 [api internal] load build definition from Dockerfile
#1 transferring dockerfile: 1.21kB done
#1 DONE 0.0s

#2 [api internal] load .dockerignore
#2 transferring context: 197B done
#2 DONE 0.0s

#3 [api internal] load metadata for docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#3 DONE 0.0s

#4 [api 1/7] FROM docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#4 DONE 0.0s

#5 [api 2/7] WORKDIR /srv/longaeva/backend
#5 CACHED

#6 [api internal] load build context
#6 transferring context: 21.24kB 0.0s done
#6 DONE 0.0s

#7 [api 3/7] RUN useradd --create-home --uid 10001 appuser     && mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config /srv/longaeva/var/artifacts /tmp     && chown -R appuser:appuser /srv/longaeva /tmp
#7 DONE 0.3s

#8 [api 4/7] COPY requirements.txt requirements-dev.txt requirements.lock ./
#8 DONE 0.0s

#9 [api 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#9 1.233 Collecting httpx<1,>=0.28.0 (from -r /srv/longaeva/backend/requirements.txt (line 1))
#9 1.328   Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
#9 1.355 Collecting pdfminer.six<20260201,>=20240706 (from -r /srv/longaeva/backend/requirements.txt (line 2))
#9 1.396   Downloading pdfminer_six-20260107-py3-none-any.whl.metadata (4.3 kB)
#9 1.470 Collecting fastapi<1,>=0.115.0 (from -r /srv/longaeva/backend/requirements.txt (line 3))
#9 1.489   Downloading fastapi-0.142.2-py3-none-any.whl.metadata (27 kB)
#9 1.538 Collecting uvicorn<1,>=0.32.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 1.556   Downloading uvicorn-0.54.0-py3-none-any.whl.metadata (6.6 kB)
#9 1.817 Collecting SQLAlchemy<2.1,>=2.0.36 (from -r /srv/longaeva/backend/requirements.txt (line 5))
#9 1.837   Downloading sqlalchemy-2.0.54-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (9.7 kB)
#9 1.871 Collecting alembic<2,>=1.14.0 (from -r /srv/longaeva/backend/requirements.txt (line 6))
#9 1.889   Downloading alembic-1.20.0-py3-none-any.whl.metadata (7.3 kB)
#9 1.917 Collecting psycopg<4,>=3.2.0 (from psycopg[binary]<4,>=3.2.0->-r /srv/longaeva/backend/requirements.txt (line 7))
#9 1.937   Downloading psycopg-3.3.6-py3-none-any.whl.metadata (4.4 kB)
#9 2.018 Collecting pydantic<3,>=2.10.0 (from -r /srv/longaeva/backend/requirements.txt (line 8))
#9 2.037   Downloading pydantic-2.13.5-py3-none-any.whl.metadata (110 kB)
#9 2.092 Collecting pydantic-settings<3,>=2.6.0 (from -r /srv/longaeva/backend/requirements.txt (line 9))
#9 2.112   Downloading pydantic_settings-2.15.0-py3-none-any.whl.metadata (3.9 kB)
#9 2.248 Collecting numpy<3,>=2.1.0 (from -r /srv/longaeva/backend/requirements.txt (line 10))
#9 2.266   Downloading numpy-2.5.3-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (6.6 kB)
#9 2.369 Collecting scipy<2,>=1.14.0 (from -r /srv/longaeva/backend/requirements.txt (line 11))
#9 2.387   Downloading scipy-1.18.1-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (62 kB)
#9 2.476 Collecting pandas<4,>=2.2.0 (from -r /srv/longaeva/backend/requirements.txt (line 12))
#9 2.503   Downloading pandas-3.0.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl.metadata (79 kB)
#9 2.558 Collecting pdfplumber<1,>=0.11.0 (from -r /srv/longaeva/backend/requirements.txt (line 13))
#9 2.580   Downloading pdfplumber-0.11.10-py3-none-any.whl.metadata (43 kB)
#9 2.614 Collecting openpyxl<4,>=3.1.0 (from -r /srv/longaeva/backend/requirements.txt (line 14))
#9 2.635   Downloading openpyxl-3.1.5-py2.py3-none-any.whl.metadata (2.5 kB)
#9 2.673 Collecting PyYAML<7,>=6.0.0 (from -r /srv/longaeva/backend/requirements.txt (line 15))
#9 2.699   Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.4 kB)
#9 2.723 Collecting xlrd<3,>=2.0.1 (from -r /srv/longaeva/backend/requirements.txt (line 16))
#9 2.747   Downloading xlrd-2.0.2-py2.py3-none-any.whl.metadata (3.5 kB)
#9 2.774 Collecting pathspec<2,>=0.12 (from -r /srv/longaeva/backend/requirements.txt (line 17))
#9 2.793   Downloading pathspec-1.1.1-py3-none-any.whl.metadata (14 kB)
#9 2.836 Collecting pytest<9,>=8.3.0 (from -r requirements-dev.txt (line 2))
#9 2.855   Downloading pytest-8.4.2-py3-none-any.whl.metadata (7.7 kB)
#9 3.105 Collecting ruff<1,>=0.9.0 (from -r requirements-dev.txt (line 3))
#9 3.124   Downloading ruff-0.16.10-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (20 kB)
#9 3.239 Collecting mypy<2,>=1.14.0 (from -r requirements-dev.txt (line 4))
#9 3.258   Downloading mypy-1.20.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.4 kB)
#9 3.285 Collecting types-psycopg2<3,>=2.9.21 (from -r requirements-dev.txt (line 5))
#9 3.309   Downloading types_psycopg2-2.9.21.20260911-py3-none-any.whl.metadata (1.8 kB)
#9 3.339 Collecting types-openpyxl<4,>=3.1.0 (from -r requirements-dev.txt (line 6))
#9 3.356   Downloading types_openpyxl-3.1.5.20260827-py3-none-any.whl.metadata (1.8 kB)
#9 3.381 Collecting types-PyYAML<7,>=6.0.0 (from -r requirements-dev.txt (line 7))
#9 3.399   Downloading types_pyyaml-6.0.12.20260906-py3-none-any.whl.metadata (1.8 kB)
#9 3.433 Collecting pandas-stubs<4,>=2.2.0 (from -r requirements-dev.txt (line 8))
#9 3.450   Downloading pandas_stubs-3.0.5.260914-py3-none-any.whl.metadata (11 kB)
#9 3.477 Collecting scipy-stubs<2,>=1.14.0 (from -r requirements-dev.txt (line 9))
#9 3.498   Downloading scipy_stubs-1.18.1.1-py3-none-any.whl.metadata (33 kB)
#9 3.528 Collecting anyio (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#9 3.551   Downloading anyio-4.15.1-py3-none-any.whl.metadata (4.7 kB)
#9 3.578 Collecting certifi (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#9 3.596   Downloading certifi-2026.7.22-py3-none-any.whl.metadata (2.5 kB)
#9 3.625 Collecting httpcore==1.* (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#9 3.644   Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
#9 3.671 Collecting idna (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#9 3.689   Downloading idna-3.20-py3-none-any.whl.metadata (7.2 kB)
#9 3.713 Collecting h11>=0.16 (from httpcore==1.*->httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#9 3.731   Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
#9 3.820 Collecting charset-normalizer>=2.0.0 (from pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#9 3.840   Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (46 kB)
#9 3.964 Collecting cryptography>=36.0.0 (from pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#9 3.984   Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_aarch64.whl.metadata (4.4 kB)
#9 4.016 Collecting starlette>=0.46.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#9 4.036   Downloading starlette-1.7.0-py3-none-any.whl.metadata (6.6 kB)
#9 4.072 Collecting typing-extensions>=4.8.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#9 4.090   Downloading typing_extensions-4.16.0-py3-none-any.whl.metadata (3.3 kB)
#9 4.113 Collecting typing-inspection>=0.4.2 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#9 4.131   Downloading typing_inspection-0.4.4-py3-none-any.whl.metadata (2.6 kB)
#9 4.154 Collecting annotated-doc>=0.0.2 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#9 4.171   Downloading annotated_doc-0.0.5-py3-none-any.whl.metadata (6.5 kB)
#9 4.202 Collecting opentelemetry-api>=1.44.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#9 4.221   Downloading opentelemetry_api-1.45.0-py3-none-any.whl.metadata (1.4 kB)
#9 4.254 Collecting click>=7.0 (from uvicorn<1,>=0.32.0->uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 4.276   Downloading click-8.5.0-py3-none-any.whl.metadata (2.6 kB)
#9 4.452 Collecting greenlet>=1 (from SQLAlchemy<2.1,>=2.0.36->-r /srv/longaeva/backend/requirements.txt (line 5))
#9 4.471   Downloading greenlet-3.5.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl.metadata (3.8 kB)
#9 4.510 Collecting Mako (from alembic<2,>=1.14.0->-r /srv/longaeva/backend/requirements.txt (line 6))
#9 4.528   Downloading mako-1.4.3-py3-none-any.whl.metadata (2.9 kB)
#9 4.555 Collecting annotated-types>=0.6.0 (from pydantic<3,>=2.10.0->-r /srv/longaeva/backend/requirements.txt (line 8))
#9 4.573   Downloading annotated_types-0.8.0-py3-none-any.whl.metadata (15 kB)
#9 5.146 Collecting pydantic-core==2.46.5 (from pydantic<3,>=2.10.0->-r /srv/longaeva/backend/requirements.txt (line 8))
#9 5.164   Downloading pydantic_core-2.46.5-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (6.6 kB)
#9 5.218 Collecting python-dotenv>=0.21.0 (from pydantic-settings<3,>=2.6.0->-r /srv/longaeva/backend/requirements.txt (line 9))
#9 5.241   Downloading python_dotenv-1.2.4-py3-none-any.whl.metadata (29 kB)
#9 5.295 Collecting python-dateutil>=2.8.2 (from pandas<4,>=2.2.0->-r /srv/longaeva/backend/requirements.txt (line 12))
#9 5.313   Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl.metadata (8.4 kB)
#9 5.483 Collecting Pillow>=12.2.0 (from pdfplumber<1,>=0.11.0->-r /srv/longaeva/backend/requirements.txt (line 13))
#9 5.504   Downloading pillow-12.3.0-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (9.1 kB)
#9 5.585 Collecting pypdfium2>=5.9.0 (from pdfplumber<1,>=0.11.0->-r /srv/longaeva/backend/requirements.txt (line 13))
#9 5.606   Downloading pypdfium2-5.13.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (66 kB)
#9 5.632 Collecting et-xmlfile (from openpyxl<4,>=3.1.0->-r /srv/longaeva/backend/requirements.txt (line 14))
#9 5.654   Downloading et_xmlfile-2.0.0-py3-none-any.whl.metadata (2.7 kB)
#9 5.677 Collecting iniconfig>=1 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#9 5.695   Downloading iniconfig-2.3.0-py3-none-any.whl.metadata (2.5 kB)
#9 5.723 Collecting packaging>=20 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#9 5.741   Downloading packaging-26.3-py3-none-any.whl.metadata (3.5 kB)
#9 5.764 Collecting pluggy<2,>=1.5 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#9 5.783   Downloading pluggy-1.6.0-py3-none-any.whl.metadata (4.8 kB)
#9 5.812 Collecting pygments>=2.7.2 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#9 5.830   Downloading pygments-2.21.0-py3-none-any.whl.metadata (2.5 kB)
#9 5.855 Collecting mypy_extensions>=1.0.0 (from mypy<2,>=1.14.0->-r requirements-dev.txt (line 4))
#9 5.874   Downloading mypy_extensions-1.1.0-py3-none-any.whl.metadata (1.1 kB)
#9 5.964 Collecting librt>=0.8.0 (from mypy<2,>=1.14.0->-r requirements-dev.txt (line 4))
#9 5.983   Downloading librt-0.16.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (1.3 kB)
#9 6.017 Collecting optype<0.20,>=0.15.0 (from optype[numpy]<0.20,>=0.15.0->scipy-stubs<2,>=1.14.0->-r requirements-dev.txt (line 9))
#9 6.037   Downloading optype-0.19.0-py3-none-any.whl.metadata (5.1 kB)
#9 6.136 Collecting psycopg-binary==3.3.6 (from psycopg[binary]<4,>=3.2.0->-r /srv/longaeva/backend/requirements.txt (line 7))
#9 6.159   Downloading psycopg_binary-3.3.6-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (2.7 kB)
#9 6.193 Collecting httptools>=0.8.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 6.210   Downloading httptools-0.8.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (3.5 kB)
#9 6.252 Collecting uvloop>=0.15.1 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 6.271   Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (5.1 kB)
#9 6.381 Collecting watchfiles>=0.20 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 6.399   Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (4.9 kB)
#9 6.484 Collecting websockets>=13.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#9 6.503   Downloading websockets-17.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (6.3 kB)
#9 6.583 Collecting cffi>=2.0.0 (from cryptography>=36.0.0->pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#9 6.601   Downloading cffi-2.1.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl.metadata (2.5 kB)
#9 6.641 Collecting numpy-typing-compat<20260603,>=20260602.2.0 (from optype[numpy]<0.20,>=0.15.0->scipy-stubs<2,>=1.14.0->-r requirements-dev.txt (line 9))
#9 6.663   Downloading numpy_typing_compat-20260602.2.5-py3-none-any.whl.metadata (6.9 kB)
#9 6.691 Collecting six>=1.5 (from python-dateutil>=2.8.2->pandas<4,>=2.2.0->-r /srv/longaeva/backend/requirements.txt (line 12))
#9 6.710   Downloading six-1.17.0-py2.py3-none-any.whl.metadata (1.7 kB)
#9 6.774 Collecting MarkupSafe>=2.0 (from Mako->alembic<2,>=1.14.0->-r /srv/longaeva/backend/requirements.txt (line 6))
#9 6.791   Downloading markupsafe-3.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.7 kB)
#9 6.812 Collecting pycparser (from cffi>=2.0.0->cryptography>=36.0.0->pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#9 6.830   Downloading pycparser-3.0-py3-none-any.whl.metadata (8.2 kB)
#9 6.862 Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
#9 6.885 Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
#9 6.907 Downloading pdfminer_six-20260107-py3-none-any.whl (6.6 MB)
#9 7.226    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.6/6.6 MB 21.7 MB/s eta 0:00:00
#9 7.247 Downloading fastapi-0.142.2-py3-none-any.whl (144 kB)
#9 7.272 Downloading uvicorn-0.54.0-py3-none-any.whl (87 kB)
#9 7.297 Downloading sqlalchemy-2.0.54-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (3.4 MB)
#9 7.433    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.4/3.4 MB 26.0 MB/s eta 0:00:00
#9 7.454 Downloading alembic-1.20.0-py3-none-any.whl (268 kB)
#9 7.484 Downloading psycopg-3.3.6-py3-none-any.whl (215 kB)
#9 7.514 Downloading pydantic-2.13.5-py3-none-any.whl (472 kB)
#9 7.556 Downloading pydantic_core-2.46.5-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (2.0 MB)
#9 7.655    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.0/2.0 MB 21.5 MB/s eta 0:00:00
#9 7.673 Downloading pydantic_settings-2.15.0-py3-none-any.whl (69 kB)
#9 7.695 Downloading numpy-2.5.3-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (15.7 MB)
#9 8.401    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 15.7/15.7 MB 22.5 MB/s eta 0:00:00
#9 8.435 Downloading scipy-1.18.1-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (34.0 MB)
#9 10.01    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 34.0/34.0 MB 21.5 MB/s eta 0:00:00
#9 10.03 Downloading pandas-3.0.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl (10.3 MB)
#9 10.74    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.3/10.3 MB 14.6 MB/s eta 0:00:00
#9 10.76 Downloading pdfplumber-0.11.10-py3-none-any.whl (60 kB)
#9 10.78 Downloading openpyxl-3.1.5-py2.py3-none-any.whl (250 kB)
#9 10.81 Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (775 kB)
#9 10.86    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 775.1/775.1 kB 15.3 MB/s eta 0:00:00
#9 10.88 Downloading xlrd-2.0.2-py2.py3-none-any.whl (96 kB)
#9 10.91 Downloading pathspec-1.1.1-py3-none-any.whl (57 kB)
#9 10.93 Downloading pytest-8.4.2-py3-none-any.whl (365 kB)
#9 10.98 Downloading ruff-0.16.10-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (9.9 MB)
#9 11.68    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 9.9/9.9 MB 14.3 MB/s eta 0:00:00
#9 11.70 Downloading mypy-1.20.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (13.7 MB)
#9 12.70    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 13.7/13.7 MB 13.8 MB/s eta 0:00:00
#9 12.73 Downloading types_psycopg2-2.9.21.20260911-py3-none-any.whl (25 kB)
#9 12.75 Downloading types_openpyxl-3.1.5.20260827-py3-none-any.whl (165 kB)
#9 12.78 Downloading types_pyyaml-6.0.12.20260906-py3-none-any.whl (21 kB)
#9 12.80 Downloading pandas_stubs-3.0.5.260914-py3-none-any.whl (177 kB)
#9 12.84 Downloading scipy_stubs-1.18.1.1-py3-none-any.whl (665 kB)
#9 12.88    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 665.2/665.2 kB 15.0 MB/s eta 0:00:00
#9 12.90 Downloading psycopg_binary-3.3.6-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (6.8 MB)
#9 13.30    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.8/6.8 MB 17.5 MB/s eta 0:00:00
#9 13.32 Downloading annotated_doc-0.0.5-py3-none-any.whl (5.3 kB)
#9 13.34 Downloading annotated_types-0.8.0-py3-none-any.whl (13 kB)
#9 13.36 Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (246 kB)
#9 13.42 Downloading click-8.5.0-py3-none-any.whl (125 kB)
#9 13.57 Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_aarch64.whl (4.7 MB)
#9 13.72    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.7/4.7 MB 34.8 MB/s eta 0:00:00
#9 13.74 Downloading greenlet-3.5.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl (611 kB)
#9 13.78    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 611.7/611.7 kB 22.8 MB/s eta 0:00:00
#9 13.80 Downloading h11-0.16.0-py3-none-any.whl (37 kB)
#9 13.82 Downloading httptools-0.8.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (518 kB)
#9 13.88 Downloading iniconfig-2.3.0-py3-none-any.whl (7.5 kB)
#9 13.91 Downloading librt-0.16.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (503 kB)
#9 14.23 Downloading mypy_extensions-1.1.0-py3-none-any.whl (5.0 kB)
#9 14.29 Downloading opentelemetry_api-1.45.0-py3-none-any.whl (60 kB)
#9 14.33 Downloading optype-0.19.0-py3-none-any.whl (141 kB)
#9 14.37 Downloading packaging-26.3-py3-none-any.whl (129 kB)
#9 14.44 Downloading pillow-12.3.0-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (6.3 MB)
#9 15.08    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.3/6.3 MB 15.3 MB/s eta 0:00:00
#9 15.11 Downloading pluggy-1.6.0-py3-none-any.whl (20 kB)
#9 15.13 Downloading pygments-2.21.0-py3-none-any.whl (1.3 MB)
#9 15.21    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.3/1.3 MB 20.5 MB/s eta 0:00:00
#9 15.25 Downloading pypdfium2-5.13.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (3.7 MB)
#9 15.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.7/3.7 MB 19.8 MB/s eta 0:00:00
#9 15.45 Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl (229 kB)
#9 15.48 Downloading python_dotenv-1.2.4-py3-none-any.whl (23 kB)
#9 15.50 Downloading starlette-1.7.0-py3-none-any.whl (78 kB)
#9 15.53 Downloading anyio-4.15.1-py3-none-any.whl (132 kB)
#9 15.64 Downloading idna-3.20-py3-none-any.whl (69 kB)
#9 15.66 Downloading typing_extensions-4.16.0-py3-none-any.whl (45 kB)
#9 15.70 Downloading typing_inspection-0.4.4-py3-none-any.whl (14 kB)
#9 15.72 Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (4.4 MB)
#9 15.98    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.4/4.4 MB 17.2 MB/s eta 0:00:00
#9 16.00 Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (454 kB)
#9 16.05 Downloading websockets-17.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (225 kB)
#9 16.08 Downloading certifi-2026.7.22-py3-none-any.whl (136 kB)
#9 16.11 Downloading et_xmlfile-2.0.0-py3-none-any.whl (18 kB)
#9 16.13 Downloading mako-1.4.3-py3-none-any.whl (80 kB)
#9 16.15 Downloading cffi-2.1.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl (222 kB)
#9 16.18 Downloading markupsafe-3.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (24 kB)
#9 16.21 Downloading numpy_typing_compat-20260602.2.5-py3-none-any.whl (5.9 kB)
#9 16.22 Downloading six-1.17.0-py2.py3-none-any.whl (11 kB)
#9 16.24 Downloading pycparser-3.0-py3-none-any.whl (48 kB)
#9 16.58 Installing collected packages: xlrd, websockets, uvloop, typing-extensions, types-PyYAML, types-psycopg2, types-openpyxl, six, ruff, PyYAML, python-dotenv, pypdfium2, pygments, pycparser, psycopg-binary, pluggy, Pillow, pathspec, packaging, numpy, mypy_extensions, MarkupSafe, librt, iniconfig, idna, httptools, h11, greenlet, et-xmlfile, click, charset-normalizer, certifi, annotated-types, annotated-doc, uvicorn, typing-inspection, SQLAlchemy, scipy, python-dateutil, pytest, pydantic-core, psycopg, pandas-stubs, optype, opentelemetry-api, openpyxl, numpy-typing-compat, mypy, Mako, httpcore, cffi, anyio, watchfiles, starlette, pydantic, pandas, httpx, cryptography, alembic, scipy-stubs, pydantic-settings, pdfminer.six, fastapi, pdfplumber
#9 32.85 Successfully installed Mako-1.4.3 MarkupSafe-3.0.3 Pillow-12.3.0 PyYAML-6.0.3 SQLAlchemy-2.0.54 alembic-1.20.0 annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.15.1 certifi-2026.7.22 cffi-2.1.1 charset-normalizer-3.5.2 click-8.5.0 cryptography-50.0.2 et-xmlfile-2.0.0 fastapi-0.142.2 greenlet-3.5.6 h11-0.16.0 httpcore-1.0.9 httptools-0.8.0 httpx-0.28.1 idna-3.20 iniconfig-2.3.0 librt-0.16.0 mypy-1.20.2 mypy_extensions-1.1.0 numpy-2.5.3 numpy-typing-compat-20260602.2.5 openpyxl-3.1.5 opentelemetry-api-1.45.0 optype-0.19.0 packaging-26.3 pandas-3.0.6 pandas-stubs-3.0.5.260914 pathspec-1.1.1 pdfminer.six-20260107 pdfplumber-0.11.10 pluggy-1.6.0 psycopg-3.3.6 psycopg-binary-3.3.6 pycparser-3.0 pydantic-2.13.5 pydantic-core-2.46.5 pydantic-settings-2.15.0 pygments-2.21.0 pypdfium2-5.13.0 pytest-8.4.2 python-dateutil-2.9.0.post0 python-dotenv-1.2.4 ruff-0.16.10 scipy-1.18.1 scipy-stubs-1.18.1.1 six-1.17.0 starlette-1.7.0 types-PyYAML-6.0.12.20260906 types-openpyxl-3.1.5.20260827 types-psycopg2-2.9.21.20260911 typing-extensions-4.16.0 typing-inspection-0.4.4 uvicorn-0.54.0 uvloop-0.23.0 watchfiles-1.3.0 websockets-17.1 xlrd-2.0.2
#9 32.85 WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
#9 32.98
#9 32.98 [notice] A new release of pip is available: 25.0.1 -> 26.2.1
#9 32.98 [notice] To update, run: pip install --upgrade pip
#9 DONE 34.2s

#10 [api 6/7] COPY --chown=appuser:appuser . /srv/longaeva/backend
#10 DONE 0.1s

#11 [api 7/7] RUN mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config     && chown -R appuser:appuser /srv/longaeva
#11 DONE 0.3s

#12 [api] exporting to image
#12 exporting layers
#12 exporting layers 2.0s done
#12 writing image sha256:a37dd6336eab54c2cec5134933d2e47f62d42a0cd7d422d469644b2a13ba1cb5 done
#12 naming to docker.io/library/longaeva-verify-9ed102-api done
#12 DONE 2.0s

#13 [worker internal] load .dockerignore
#13 transferring context: 197B done
#13 DONE 0.0s

#14 [worker internal] load build definition from Dockerfile
#14 transferring dockerfile: 1.21kB done
#14 DONE 0.0s

#3 [worker internal] load metadata for docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#3 DONE 0.0s

#4 [worker 1/7] FROM docker.io/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3
#4 DONE 0.0s

#5 [worker 2/7] WORKDIR /srv/longaeva/backend
#5 CACHED

#15 [web internal] load build definition from Dockerfile
#15 transferring dockerfile: 547B done
#15 DONE 0.0s

#16 [web internal] load .dockerignore
#16 transferring context: 143B done
#16 DONE 0.0s

#17 [worker internal] load build context
#17 transferring context: 21.24kB 0.0s done
#17 DONE 0.0s

#18 [web internal] load metadata for docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#18 DONE 0.0s

#19 [web internal] load metadata for docker.io/library/nginx:1.27-alpine
#19 DONE 0.0s

#20 [web frontend-src 1/5] FROM docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#20 DONE 0.0s

#21 [web stage-3 1/3] FROM docker.io/library/nginx:1.27-alpine
#21 DONE 0.0s

#22 [web frontend-src 2/5] WORKDIR /app
#22 CACHED

#23 [web internal] load build context
#23 transferring context: 6.84kB done
#23 DONE 0.0s

#21 [web stage-3 1/3] FROM docker.io/library/nginx:1.27-alpine
#21 CACHED

#24 [web stage-3 2/3] COPY nginx.conf /etc/nginx/conf.d/default.conf
#24 DONE 0.1s

#25 [web frontend-src 3/5] COPY package.json package-lock.json ./
#25 DONE 0.1s

#26 [web frontend-src 4/5] RUN npm ci
#26 ...

#7 [worker 3/7] RUN useradd --create-home --uid 10001 appuser     && mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config /srv/longaeva/var/artifacts /tmp     && chown -R appuser:appuser /srv/longaeva /tmp
#7 DONE 0.6s

#27 [worker 4/7] COPY requirements.txt requirements-dev.txt requirements.lock ./
#27 DONE 0.1s

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 5.352 Collecting httpx<1,>=0.28.0 (from -r /srv/longaeva/backend/requirements.txt (line 1))
#28 5.493   Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
#28 5.531 Collecting pdfminer.six<20260201,>=20240706 (from -r /srv/longaeva/backend/requirements.txt (line 2))
#28 5.553   Downloading pdfminer_six-20260107-py3-none-any.whl.metadata (4.3 kB)
#28 5.625 Collecting fastapi<1,>=0.115.0 (from -r /srv/longaeva/backend/requirements.txt (line 3))
#28 5.644   Downloading fastapi-0.142.2-py3-none-any.whl.metadata (27 kB)
#28 5.700 Collecting uvicorn<1,>=0.32.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 5.736   Downloading uvicorn-0.54.0-py3-none-any.whl.metadata (6.6 kB)
#28 7.115 Collecting SQLAlchemy<2.1,>=2.0.36 (from -r /srv/longaeva/backend/requirements.txt (line 5))
#28 7.138   Downloading sqlalchemy-2.0.54-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (9.7 kB)
#28 7.183 Collecting alembic<2,>=1.14.0 (from -r /srv/longaeva/backend/requirements.txt (line 6))
#28 7.313   Downloading alembic-1.20.0-py3-none-any.whl.metadata (7.3 kB)
#28 7.456 Collecting psycopg<4,>=3.2.0 (from psycopg[binary]<4,>=3.2.0->-r /srv/longaeva/backend/requirements.txt (line 7))
#28 7.493   Downloading psycopg-3.3.6-py3-none-any.whl.metadata (4.4 kB)
#28 7.669 Collecting pydantic<3,>=2.10.0 (from -r /srv/longaeva/backend/requirements.txt (line 8))
#28 7.688   Downloading pydantic-2.13.5-py3-none-any.whl.metadata (110 kB)
#28 7.748 Collecting pydantic-settings<3,>=2.6.0 (from -r /srv/longaeva/backend/requirements.txt (line 9))
#28 7.768   Downloading pydantic_settings-2.15.0-py3-none-any.whl.metadata (3.9 kB)
#28 7.964 Collecting numpy<3,>=2.1.0 (from -r /srv/longaeva/backend/requirements.txt (line 10))
#28 8.016   Downloading numpy-2.5.3-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (6.6 kB)
#28 8.277 Collecting scipy<2,>=1.14.0 (from -r /srv/longaeva/backend/requirements.txt (line 11))
#28 8.319   Downloading scipy-1.18.1-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (62 kB)
#28 8.677 Collecting pandas<4,>=2.2.0 (from -r /srv/longaeva/backend/requirements.txt (line 12))
#28 8.697   Downloading pandas-3.0.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl.metadata (79 kB)
#28 8.764 Collecting pdfplumber<1,>=0.11.0 (from -r /srv/longaeva/backend/requirements.txt (line 13))
#28 8.786   Downloading pdfplumber-0.11.10-py3-none-any.whl.metadata (43 kB)
#28 8.830 Collecting openpyxl<4,>=3.1.0 (from -r /srv/longaeva/backend/requirements.txt (line 14))
#28 8.848   Downloading openpyxl-3.1.5-py2.py3-none-any.whl.metadata (2.5 kB)
#28 8.897 Collecting PyYAML<7,>=6.0.0 (from -r /srv/longaeva/backend/requirements.txt (line 15))
#28 8.923   Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.4 kB)
#28 8.951 Collecting xlrd<3,>=2.0.1 (from -r /srv/longaeva/backend/requirements.txt (line 16))
#28 8.976   Downloading xlrd-2.0.2-py2.py3-none-any.whl.metadata (3.5 kB)
#28 9.005 Collecting pathspec<2,>=0.12 (from -r /srv/longaeva/backend/requirements.txt (line 17))
#28 9.024   Downloading pathspec-1.1.1-py3-none-any.whl.metadata (14 kB)
#28 9.081 Collecting pytest<9,>=8.3.0 (from -r requirements-dev.txt (line 2))
#28 9.124   Downloading pytest-8.4.2-py3-none-any.whl.metadata (7.7 kB)
#28 10.16 Collecting ruff<1,>=0.9.0 (from -r requirements-dev.txt (line 3))
#28 10.23   Downloading ruff-0.16.10-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (20 kB)
#28 10.48 Collecting mypy<2,>=1.14.0 (from -r requirements-dev.txt (line 4))
#28 10.58   Downloading mypy-1.20.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.4 kB)
#28 10.79 Collecting types-psycopg2<3,>=2.9.21 (from -r requirements-dev.txt (line 5))
#28 10.82   Downloading types_psycopg2-2.9.21.20260911-py3-none-any.whl.metadata (1.8 kB)
#28 10.86 Collecting types-openpyxl<4,>=3.1.0 (from -r requirements-dev.txt (line 6))
#28 10.90   Downloading types_openpyxl-3.1.5.20260827-py3-none-any.whl.metadata (1.8 kB)
#28 10.95 Collecting types-PyYAML<7,>=6.0.0 (from -r requirements-dev.txt (line 7))
#28 10.98   Downloading types_pyyaml-6.0.12.20260906-py3-none-any.whl.metadata (1.8 kB)
#28 11.05 Collecting pandas-stubs<4,>=2.2.0 (from -r requirements-dev.txt (line 8))
#28 11.09   Downloading pandas_stubs-3.0.5.260914-py3-none-any.whl.metadata (11 kB)
#28 11.14 Collecting scipy-stubs<2,>=1.14.0 (from -r requirements-dev.txt (line 9))
#28 11.16   Downloading scipy_stubs-1.18.1.1-py3-none-any.whl.metadata (33 kB)
#28 11.23 Collecting anyio (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#28 11.25   Downloading anyio-4.15.1-py3-none-any.whl.metadata (4.7 kB)
#28 11.33 Collecting certifi (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#28 11.36   Downloading certifi-2026.7.22-py3-none-any.whl.metadata (2.5 kB)
#28 11.40 Collecting httpcore==1.* (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#28 11.42   Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
#28 11.45 Collecting idna (from httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#28 11.47   Downloading idna-3.20-py3-none-any.whl.metadata (7.2 kB)
#28 11.50 Collecting h11>=0.16 (from httpcore==1.*->httpx<1,>=0.28.0->-r /srv/longaeva/backend/requirements.txt (line 1))
#28 11.52   Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
#28 11.67 Collecting charset-normalizer>=2.0.0 (from pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#28 11.69   Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (46 kB)
#28 12.03 Collecting cryptography>=36.0.0 (from pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#28 12.06   Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_aarch64.whl.metadata (4.4 kB)
#28 12.12 Collecting starlette>=0.46.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#28 12.14   Downloading starlette-1.7.0-py3-none-any.whl.metadata (6.6 kB)
#28 12.20 Collecting typing-extensions>=4.8.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#28 12.22   Downloading typing_extensions-4.16.0-py3-none-any.whl.metadata (3.3 kB)
#28 12.25 Collecting typing-inspection>=0.4.2 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#28 12.27   Downloading typing_inspection-0.4.4-py3-none-any.whl.metadata (2.6 kB)
#28 12.30 Collecting annotated-doc>=0.0.2 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#28 12.31   Downloading annotated_doc-0.0.5-py3-none-any.whl.metadata (6.5 kB)
#28 12.38 Collecting opentelemetry-api>=1.44.0 (from fastapi<1,>=0.115.0->-r /srv/longaeva/backend/requirements.txt (line 3))
#28 12.42   Downloading opentelemetry_api-1.45.0-py3-none-any.whl.metadata (1.4 kB)
#28 12.62 Collecting click>=7.0 (from uvicorn<1,>=0.32.0->uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 12.73   Downloading click-8.5.0-py3-none-any.whl.metadata (2.6 kB)
#28 13.55 Collecting greenlet>=1 (from SQLAlchemy<2.1,>=2.0.36->-r /srv/longaeva/backend/requirements.txt (line 5))
#28 13.58   Downloading greenlet-3.5.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl.metadata (3.8 kB)
#28 13.70 Collecting Mako (from alembic<2,>=1.14.0->-r /srv/longaeva/backend/requirements.txt (line 6))
#28 13.75   Downloading mako-1.4.3-py3-none-any.whl.metadata (2.9 kB)
#28 13.80 Collecting annotated-types>=0.6.0 (from pydantic<3,>=2.10.0->-r /srv/longaeva/backend/requirements.txt (line 8))
#28 13.82   Downloading annotated_types-0.8.0-py3-none-any.whl.metadata (15 kB)
#28 15.00 Collecting pydantic-core==2.46.5 (from pydantic<3,>=2.10.0->-r /srv/longaeva/backend/requirements.txt (line 8))
#28 15.07   Downloading pydantic_core-2.46.5-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (6.6 kB)
#28 15.14 Collecting python-dotenv>=0.21.0 (from pydantic-settings<3,>=2.6.0->-r /srv/longaeva/backend/requirements.txt (line 9))
#28 15.17   Downloading python_dotenv-1.2.4-py3-none-any.whl.metadata (29 kB)
#28 15.22 Collecting python-dateutil>=2.8.2 (from pandas<4,>=2.2.0->-r /srv/longaeva/backend/requirements.txt (line 12))
#28 15.26   Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl.metadata (8.4 kB)
#28 15.52 Collecting Pillow>=12.2.0 (from pdfplumber<1,>=0.11.0->-r /srv/longaeva/backend/requirements.txt (line 13))
#28 15.54   Downloading pillow-12.3.0-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (9.1 kB)
#28 15.72 Collecting pypdfium2>=5.9.0 (from pdfplumber<1,>=0.11.0->-r /srv/longaeva/backend/requirements.txt (line 13))
#28 15.77   Downloading pypdfium2-5.13.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (66 kB)
#28 15.82 Collecting et-xmlfile (from openpyxl<4,>=3.1.0->-r /srv/longaeva/backend/requirements.txt (line 14))
#28 15.85   Downloading et_xmlfile-2.0.0-py3-none-any.whl.metadata (2.7 kB)
#28 15.89 Collecting iniconfig>=1 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#28 15.96   Downloading iniconfig-2.3.0-py3-none-any.whl.metadata (2.5 kB)
#28 16.02 Collecting packaging>=20 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#28 16.07   Downloading packaging-26.3-py3-none-any.whl.metadata (3.5 kB)
#28 16.16 Collecting pluggy<2,>=1.5 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#28 16.18   Downloading pluggy-1.6.0-py3-none-any.whl.metadata (4.8 kB)
#28 16.23 Collecting pygments>=2.7.2 (from pytest<9,>=8.3.0->-r requirements-dev.txt (line 2))
#28 16.25   Downloading pygments-2.21.0-py3-none-any.whl.metadata (2.5 kB)
#28 16.29 Collecting mypy_extensions>=1.0.0 (from mypy<2,>=1.14.0->-r requirements-dev.txt (line 4))
#28 16.31   Downloading mypy_extensions-1.1.0-py3-none-any.whl.metadata (1.1 kB)
#28 16.57 Collecting librt>=0.8.0 (from mypy<2,>=1.14.0->-r requirements-dev.txt (line 4))
#28 16.68   Downloading librt-0.16.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (1.3 kB)
#28 16.98 Collecting optype<0.20,>=0.15.0 (from optype[numpy]<0.20,>=0.15.0->scipy-stubs<2,>=1.14.0->-r requirements-dev.txt (line 9))
#28 17.01   Downloading optype-0.19.0-py3-none-any.whl.metadata (5.1 kB)
#28 17.24 Collecting psycopg-binary==3.3.6 (from psycopg[binary]<4,>=3.2.0->-r /srv/longaeva/backend/requirements.txt (line 7))
#28 17.27   Downloading psycopg_binary-3.3.6-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl.metadata (2.7 kB)
#28 17.32 Collecting httptools>=0.8.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 17.34   Downloading httptools-0.8.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (3.5 kB)
#28 17.56 Collecting uvloop>=0.15.1 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 17.59   Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (5.1 kB)
#28 17.68 Collecting watchfiles>=0.20 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 17.71   Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl.metadata (4.9 kB)
#28 17.84 Collecting websockets>=13.0 (from uvicorn[standard]<1,>=0.32.0->-r /srv/longaeva/backend/requirements.txt (line 4))
#28 17.87   Downloading websockets-17.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (6.3 kB)
#28 18.00 Collecting cffi>=2.0.0 (from cryptography>=36.0.0->pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#28 18.02   Downloading cffi-2.1.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl.metadata (2.5 kB)
#28 18.07 Collecting numpy-typing-compat<20260603,>=20260602.2.0 (from optype[numpy]<0.20,>=0.15.0->scipy-stubs<2,>=1.14.0->-r requirements-dev.txt (line 9))
#28 18.09   Downloading numpy_typing_compat-20260602.2.5-py3-none-any.whl.metadata (6.9 kB)
#28 18.13 Collecting six>=1.5 (from python-dateutil>=2.8.2->pandas<4,>=2.2.0->-r /srv/longaeva/backend/requirements.txt (line 12))
#28 18.19   Downloading six-1.17.0-py2.py3-none-any.whl.metadata (1.7 kB)
#28 18.29 Collecting MarkupSafe>=2.0 (from Mako->alembic<2,>=1.14.0->-r /srv/longaeva/backend/requirements.txt (line 6))
#28 18.32   Downloading markupsafe-3.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl.metadata (2.7 kB)
#28 18.34 Collecting pycparser (from cffi>=2.0.0->cryptography>=36.0.0->pdfminer.six<20260201,>=20240706->-r /srv/longaeva/backend/requirements.txt (line 2))
#28 18.37   Downloading pycparser-3.0-py3-none-any.whl.metadata (8.2 kB)
#28 18.44 Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
#28 18.47 Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
#28 18.51 Downloading pdfminer_six-20260107-py3-none-any.whl (6.6 MB)
#28 18.97    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.6/6.6 MB 14.6 MB/s eta 0:00:00
#28 19.01 Downloading fastapi-0.142.2-py3-none-any.whl (144 kB)
#28 19.04 Downloading uvicorn-0.54.0-py3-none-any.whl (87 kB)
#28 19.07 Downloading sqlalchemy-2.0.54-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (3.4 MB)
#28 19.35    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.4/3.4 MB 12.5 MB/s eta 0:00:00
#28 19.38 Downloading alembic-1.20.0-py3-none-any.whl (268 kB)
#28 19.41 Downloading psycopg-3.3.6-py3-none-any.whl (215 kB)
#28 19.45 Downloading pydantic-2.13.5-py3-none-any.whl (472 kB)
#28 19.50 Downloading pydantic_core-2.46.5-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (2.0 MB)
#28 19.66    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.0/2.0 MB 99.1 MB/s eta 0:00:00
#28 19.69 Downloading pydantic_settings-2.15.0-py3-none-any.whl (69 kB)
#28 19.72 Downloading numpy-2.5.3-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (15.7 MB)
#28 20.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 15.7/15.7 MB 22.9 MB/s eta 0:00:00
#28 20.49 Downloading scipy-1.18.1-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (34.0 MB)
#28 ...

#26 [web frontend-src 4/5] RUN npm ci
#26 21.85 npm warn deprecated eslint@9.39.3: This version is no longer supported. Please see https://eslint.org/version-support for other options.
#26 ...

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 22.44    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 34.0/34.0 MB 17.4 MB/s eta 0:00:00
#28 22.47 Downloading pandas-3.0.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl (10.3 MB)
#28 22.88    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.3/10.3 MB 25.8 MB/s eta 0:00:00
#28 22.90 Downloading pdfplumber-0.11.10-py3-none-any.whl (60 kB)
#28 22.92 Downloading openpyxl-3.1.5-py2.py3-none-any.whl (250 kB)
#28 22.97 Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (775 kB)
#28 23.03    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 775.1/775.1 kB 17.0 MB/s eta 0:00:00
#28 23.05 Downloading xlrd-2.0.2-py2.py3-none-any.whl (96 kB)
#28 23.08 Downloading pathspec-1.1.1-py3-none-any.whl (57 kB)
#28 23.10 Downloading pytest-8.4.2-py3-none-any.whl (365 kB)
#28 23.15 Downloading ruff-0.16.10-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (9.9 MB)
#28 23.64    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 9.9/9.9 MB 20.6 MB/s eta 0:00:00
#28 23.67 Downloading mypy-1.20.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (13.7 MB)
#28 24.45    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 13.7/13.7 MB 18.0 MB/s eta 0:00:00
#28 24.47 Downloading types_psycopg2-2.9.21.20260911-py3-none-any.whl (25 kB)
#28 24.53 Downloading types_openpyxl-3.1.5.20260827-py3-none-any.whl (165 kB)
#28 24.57 Downloading types_pyyaml-6.0.12.20260906-py3-none-any.whl (21 kB)
#28 25.37 Downloading pandas_stubs-3.0.5.260914-py3-none-any.whl (177 kB)
#28 25.46 Downloading scipy_stubs-1.18.1.1-py3-none-any.whl (665 kB)
#28 25.54    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 665.2/665.2 kB 75.6 MB/s eta 0:00:00
#28 25.57 Downloading psycopg_binary-3.3.6-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (6.8 MB)
#28 26.04    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.8/6.8 MB 14.9 MB/s eta 0:00:00
#28 26.06 Downloading annotated_doc-0.0.5-py3-none-any.whl (5.3 kB)
#28 26.09 Downloading annotated_types-0.8.0-py3-none-any.whl (13 kB)
#28 26.13 Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (246 kB)
#28 26.16 Downloading click-8.5.0-py3-none-any.whl (125 kB)
#28 26.20 Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_aarch64.whl (4.7 MB)
#28 26.53    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.7/4.7 MB 14.1 MB/s eta 0:00:00
#28 26.56 Downloading greenlet-3.5.6-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl (611 kB)
#28 26.60    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 611.7/611.7 kB 13.7 MB/s eta 0:00:00
#28 26.63 Downloading h11-0.16.0-py3-none-any.whl (37 kB)
#28 26.67 Downloading httptools-0.8.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (518 kB)
#28 26.74 Downloading iniconfig-2.3.0-py3-none-any.whl (7.5 kB)
#28 26.76 Downloading librt-0.16.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (503 kB)
#28 26.81 Downloading mypy_extensions-1.1.0-py3-none-any.whl (5.0 kB)
#28 26.84 Downloading opentelemetry_api-1.45.0-py3-none-any.whl (60 kB)
#28 26.87 Downloading optype-0.19.0-py3-none-any.whl (141 kB)
#28 26.89 Downloading packaging-26.3-py3-none-any.whl (129 kB)
#28 26.92 Downloading pillow-12.3.0-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl (6.3 MB)
#28 27.45    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.3/6.3 MB 12.2 MB/s eta 0:00:00
#28 27.48 Downloading pluggy-1.6.0-py3-none-any.whl (20 kB)
#28 27.50 Downloading pygments-2.21.0-py3-none-any.whl (1.3 MB)
#28 27.58    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.3/1.3 MB 16.6 MB/s eta 0:00:00
#28 27.61 Downloading pypdfium2-5.13.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (3.7 MB)
#28 27.88    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.7/3.7 MB 13.6 MB/s eta 0:00:00
#28 27.91 Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl (229 kB)
#28 27.95 Downloading python_dotenv-1.2.4-py3-none-any.whl (23 kB)
#28 27.97 Downloading starlette-1.7.0-py3-none-any.whl (78 kB)
#28 28.00 Downloading anyio-4.15.1-py3-none-any.whl (132 kB)
#28 28.04 Downloading idna-3.20-py3-none-any.whl (69 kB)
#28 28.07 Downloading typing_extensions-4.16.0-py3-none-any.whl (45 kB)
#28 28.10 Downloading typing_inspection-0.4.4-py3-none-any.whl (14 kB)
#28 28.13 Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (4.4 MB)
#28 ...

#26 [web frontend-src 4/5] RUN npm ci
#26 27.90
#26 27.90 added 373 packages, and audited 374 packages in 27s
#26 27.90
#26 27.90 151 packages are looking for funding
#26 27.90   run `npm fund` for details
#26 27.94
#26 27.94 5 vulnerabilities (2 moderate, 1 high, 2 critical)
#26 27.94
#26 27.94 To address all issues, run:
#26 27.94   npm audit fix --force
#26 27.94
#26 27.94 Run `npm audit` for details.
#26 27.94 npm notice
#26 27.94 npm notice New major version of npm available! 10.9.9 -> 12.2.0
#26 27.94 npm notice Changelog: https://github.com/npm/cli/releases/tag/v12.2.0
#26 27.94 npm notice To update run: npm install -g npm@12.2.0
#26 27.94 npm notice
#26 DONE 28.7s

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 28.46    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.4/4.4 MB 13.4 MB/s eta 0:00:00
#28 28.49 Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl (454 kB)
#28 28.54 Downloading websockets-17.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (225 kB)
#28 ...

#29 [web frontend-src 5/5] COPY . .
#29 DONE 0.3s

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 28.58 Downloading certifi-2026.7.22-py3-none-any.whl (136 kB)
#28 28.61 Downloading et_xmlfile-2.0.0-py3-none-any.whl (18 kB)
#28 28.63 Downloading mako-1.4.3-py3-none-any.whl (80 kB)
#28 28.68 Downloading cffi-2.1.1-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl (222 kB)
#28 28.73 Downloading markupsafe-3.0.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl (24 kB)
#28 28.78 Downloading numpy_typing_compat-20260602.2.5-py3-none-any.whl (5.9 kB)
#28 28.81 Downloading six-1.17.0-py2.py3-none-any.whl (11 kB)
#28 28.83 Downloading pycparser-3.0-py3-none-any.whl (48 kB)
#28 29.24 Installing collected packages: xlrd, websockets, uvloop, typing-extensions, types-PyYAML, types-psycopg2, types-openpyxl, six, ruff, PyYAML, python-dotenv, pypdfium2, pygments, pycparser, psycopg-binary, pluggy, Pillow, pathspec, packaging, numpy, mypy_extensions, MarkupSafe, librt, iniconfig, idna, httptools, h11, greenlet, et-xmlfile, click, charset-normalizer, certifi, annotated-types, annotated-doc, uvicorn, typing-inspection, SQLAlchemy, scipy, python-dateutil, pytest, pydantic-core, psycopg, pandas-stubs, optype, opentelemetry-api, openpyxl, numpy-typing-compat, mypy, Mako, httpcore, cffi, anyio, watchfiles, starlette, pydantic, pandas, httpx, cryptography, alembic, scipy-stubs, pydantic-settings, pdfminer.six, fastapi, pdfplumber
#28 ...

#30 [web build 1/1] RUN npm run build
#0 0.348
#0 0.348 > longaeva-web@0.1.0 build
#0 0.348 > tsc -b && vite build
#0 0.348
#0 7.196 vite v8.0.16 building client environment for production...
#0 7.215 [2K
transforming...✓ 866 modules transformed.
#0 7.812 rendering chunks...
#0 7.991 computing gzip size...
#0 8.003 dist/index.html                   0.78 kB │ gzip:   0.41 kB
#0 8.003 dist/assets/index-yKIoEsLg.css   35.86 kB │ gzip:   8.02 kB
#0 8.003 dist/assets/index-CVnNGdUN.js   894.22 kB │ gzip: 262.91 kB
#0 8.003
#0 8.004 [plugin builtin:vite-reporter]
#0 8.004 (!) Some chunks are larger than 500 kB after minification. Consider:
#0 8.004 - Using dynamic import() to code-split the application
#0 8.004 - Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
#0 8.004 - Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
#0 8.005 ✓ built in 806ms
#30 DONE 8.6s

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 ...

#31 [web stage-3 3/3] COPY --from=build /app/dist /usr/share/nginx/html
#31 DONE 0.0s

#32 [web] exporting to image
#32 exporting layers 0.0s done
#32 writing image sha256:aae3cf3cf88584fcd907e0b22c21f07dfe08d0723e48537a2ecdcab09c5362ca done
#32 naming to docker.io/library/longaeva-verify-9ed102-web done
#32 DONE 0.0s

#28 [worker 5/7] RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock
#28 44.86 Successfully installed Mako-1.4.3 MarkupSafe-3.0.3 Pillow-12.3.0 PyYAML-6.0.3 SQLAlchemy-2.0.54 alembic-1.20.0 annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.15.1 certifi-2026.7.22 cffi-2.1.1 charset-normalizer-3.5.2 click-8.5.0 cryptography-50.0.2 et-xmlfile-2.0.0 fastapi-0.142.2 greenlet-3.5.6 h11-0.16.0 httpcore-1.0.9 httptools-0.8.0 httpx-0.28.1 idna-3.20 iniconfig-2.3.0 librt-0.16.0 mypy-1.20.2 mypy_extensions-1.1.0 numpy-2.5.3 numpy-typing-compat-20260602.2.5 openpyxl-3.1.5 opentelemetry-api-1.45.0 optype-0.19.0 packaging-26.3 pandas-3.0.6 pandas-stubs-3.0.5.260914 pathspec-1.1.1 pdfminer.six-20260107 pdfplumber-0.11.10 pluggy-1.6.0 psycopg-3.3.6 psycopg-binary-3.3.6 pycparser-3.0 pydantic-2.13.5 pydantic-core-2.46.5 pydantic-settings-2.15.0 pygments-2.21.0 pypdfium2-5.13.0 pytest-8.4.2 python-dateutil-2.9.0.post0 python-dotenv-1.2.4 ruff-0.16.10 scipy-1.18.1 scipy-stubs-1.18.1.1 six-1.17.0 starlette-1.7.0 types-PyYAML-6.0.12.20260906 types-openpyxl-3.1.5.20260827 types-psycopg2-2.9.21.20260911 typing-extensions-4.16.0 typing-inspection-0.4.4 uvicorn-0.54.0 uvloop-0.23.0 watchfiles-1.3.0 websockets-17.1 xlrd-2.0.2
#28 44.86 WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
#28 44.97
#28 44.97 [notice] A new release of pip is available: 25.0.1 -> 26.2.1
#28 44.97 [notice] To update, run: pip install --upgrade pip
#28 DONE 45.7s

#33 [worker 6/7] COPY --chown=appuser:appuser . /srv/longaeva/backend
#33 DONE 0.1s

#34 [worker 7/7] RUN mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config     && chown -R appuser:appuser /srv/longaeva
#34 DONE 1.0s

#35 [worker] exporting to image
#35 exporting layers
#35 exporting layers 1.9s done
#35 writing image sha256:ffa28aac737a3eac8b213770fbf27576a30307caf58a3f1b868f976be8651701 0.0s done
#35 naming to docker.io/library/longaeva-verify-9ed102-worker
#35 naming to docker.io/library/longaeva-verify-9ed102-worker done
#35 DONE 1.9s
docker compose up -d --wait db
 Container longaeva-verify-9ed102-db-1  Creating
 Container longaeva-verify-9ed102-db-1  Created
 Container longaeva-verify-9ed102-db-1  Starting
 Container longaeva-verify-9ed102-db-1  Started
 Container longaeva-verify-9ed102-db-1  Waiting
 Container longaeva-verify-9ed102-db-1  Healthy
docker compose run --rm --no-deps \
		-v "/private/tmp/longaeva-verify.61aiBi/longaeva:/srv/longaeva-src:ro" -e LONGAEVA_GUARD_ROOT=/srv/longaeva-src \
		-e DATABASE_URL=postgresql://longaeva:longaeva@db:5432/longaeva \
		-e LONGAEVA_REQUIRE_DB=1 \
		-e LONGAEVA_TEST_DB=longaeva_test \
		api sh -c 'scripts/check.sh'
== ruff check ==
All checks passed!
== ruff format --check ==
213 files already formatted
== mypy ==
Success: no issues found in 205 source files
== pytest ==
........................................................................ [ 13%]
........................................................................ [ 26%]
........................................................................ [ 39%]
........................................................................ [ 52%]
........................................................................ [ 65%]
........................................................................ [ 78%]
........................................................................ [ 91%]
...............................................                          [100%]
=============================== warnings summary ===============================
../../../usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1
  /usr/local/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_ablations.py::test_matched_variants_numerical_removal_replay_and_idempotency
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
tests/test_migrations.py::test_migrations_upgrade_downgrade_upgrade
  /usr/local/lib/python3.12/site-packages/alembic/config.py:604: DeprecationWarning: No path_separator found in configuration; falling back to legacy splitting on spaces, commas, and colons for prepend_sys_path.  Consider adding path_separator=os to Alembic config.
    util.warn_deprecated(

tests/test_extract_api.py::test_extraction_is_disabled_until_a_provider_is_configured
tests/test_search.py::test_invalid_queries_return_422
  /usr/local/lib/python3.12/site-packages/fastapi/telemetry/_api.py:240: StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
    return function(**arguments)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
551 passed, 8 warnings in 223.93s (0:03:43)
/Library/Developer/CommandLineTools/usr/bin/make check-web
docker build --no-cache --target check -t longaeva-verify-9ed102-web-check ./frontend
#1 [internal] load .dockerignore
#1 transferring context: 143B 0.0s done
#1 DONE 0.0s

#2 [internal] load build definition from Dockerfile
#2 transferring dockerfile: 547B 0.0s done
#2 DONE 0.0s

#3 [internal] load metadata for docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#3 DONE 0.0s

#4 [frontend-src 1/5] FROM docker.io/library/node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c
#4 DONE 0.0s

#5 [frontend-src 2/5] WORKDIR /app
#5 CACHED

#6 [internal] load build context
#6 transferring context: 221.65kB 0.0s done
#6 DONE 0.0s

#7 [frontend-src 3/5] COPY package.json package-lock.json ./
#7 DONE 0.1s

#8 [frontend-src 4/5] RUN npm ci
#8 5.771 npm warn deprecated eslint@9.39.3: This version is no longer supported. Please see https://eslint.org/version-support for other options.
#8 7.509
#8 7.509 added 373 packages, and audited 374 packages in 7s
#8 7.509
#8 7.509 151 packages are looking for funding
#8 7.509   run `npm fund` for details
#8 7.536
#8 7.536 5 vulnerabilities (2 moderate, 1 high, 2 critical)
#8 7.536
#8 7.536 To address all issues, run:
#8 7.536   npm audit fix --force
#8 7.536
#8 7.536 Run `npm audit` for details.
#8 7.536 npm notice
#8 7.536 npm notice New major version of npm available! 10.9.9 -> 12.2.0
#8 7.536 npm notice Changelog: https://github.com/npm/cli/releases/tag/v12.2.0
#8 7.536 npm notice To update run: npm install -g npm@12.2.0
#8 7.536 npm notice
#8 DONE 8.1s

#9 [frontend-src 5/5] COPY . .
#9 DONE 0.1s

#10 exporting to image
#10 exporting layers
#10 exporting layers 1.3s done
#10 writing image sha256:e0f9e824d3ba0472f0d50160a2df71d6d4e199eb622c7f2d66d30ff7198985cb done
#10 naming to docker.io/library/longaeva-verify-9ed102-web-check done
#10 DONE 1.3s
docker run --rm longaeva-verify-9ed102-web-check sh -c 'npm run lint && npm test'

> longaeva-web@0.1.0 lint
> eslint .


> longaeva-web@0.1.0 test
> vitest run --config vitest.config.ts


 RUN  v3.2.4 /app

 ✓ src/lib/tour.test.ts (8 tests | 1 skipped) 63ms
 ✓ src/lib/scenarios.test.ts (9 tests) 68ms
 ✓ src/lib/reportDisplay.test.ts (7 tests) 52ms
 ✓ src/lib/runs.test.ts (4 tests) 4ms
 ✓ src/lib/evidence.test.ts (5 tests) 15ms
 ✓ src/lib/prospectiveDisplay.test.ts (2 tests) 36ms
 ✓ src/lib/api.test.ts (3 tests) 13ms
 ✓ src/lib/reportApi.test.ts (2 tests) 8ms
 ✓ src/lib/llmBaselineDisplay.test.ts (1 test) 46ms
 ✓ src/lib/format.test.ts (3 tests) 30ms

 Test Files  10 passed (10)
      Tests  43 passed | 1 skipped (44)
   Start at  19:13:42
   Duration  2.39s (transform 1.06s, setup 0ms, collect 2.06s, tests 335ms, environment 3ms, prepare 1.09s)
```

### final demo

```json
{
  "forecast_counts": {
    "prospective": 20,
    "retrospective": 40
  },
  "inventory_files": 191,
  "n_scored": 16,
  "new_run_ids": [
    "12c847ab-f377-445f-8a8d-cc7bda139ac5",
    "c2b46822-d556-4a8c-be06-ae70ea291fa4",
    "25173825-9060-4972-84f3-8e99a1e121db"
  ],
  "origins": [
    "2024-07-23",
    "2025-10-28"
  ],
  "replays": [
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "1259b6e2c777488cb487f105cd403eb3697e1c0fea9f5fb19a3e8801e27eff61",
      "run_id": "cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "27ab77ba607d6b306ff663640f26c75328d18efd72d86f3e474099602ffe833b",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7d1a0038211fe48e5baaca8f478163fc4f189248db80dc8460f624f681b52bc7",
      "run_id": "846c4e0b-a634-5bed-996d-3785bb899846",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "4b25be2523ca4d10556ad31fcb3eeaf7aee8b24fc0fe569e5703f8a235097b10",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "88105420099244c4504aab3641ec9ecaca8c2c6090cb8a8cce42172a72c6448a",
      "run_id": "fbbad1df-6531-4a41-86e0-32dda8a482c2",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "361799585560f720b65f7108b1d0bc4c04fd94ca7ab78ce6965a39d032ddc15f",
      "run_id": "3752b7df-c114-5fa4-b312-efe5a5908c38",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "fa1c7bd0d747eef14b1e68ad3f8db9c5b8e789a3e86432d8dd2298361c54faea",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "98dba6f33fb6603e8f4561aeeae34ff6583af5963d2aca77099fffa82bbe075c",
      "run_id": "db0ff361-957b-5148-8299-6c71d0313f57",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.5543122344752192e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "5dabe0961f0d9e5d21f28647be5e6edf49246a40ef0cf44f26438cf00ef12b24",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "a9663464147616255f391896b450513809a174744df5ef360bb83aa0542bacf7",
      "run_id": "20673695-fcda-54a8-8020-3d670ee80847",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 2.1094237467877974e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "04a0ff13875572e677cd36a0694a6d616aadfe79e2b06b19e1c9b63862d13c1f",
      "run_id": "ab595be3-2964-5845-b6f3-4d8d4fce6bf3",
      "status": "numerically_equivalent"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "run_id": "12c847ab-f377-445f-8a8d-cc7bda139ac5",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "run_id": "c2b46822-d556-4a8c-be06-ae70ea291fa4",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "run_id": "25173825-9060-4972-84f3-8e99a1e121db",
      "status": "exact_match"
    }
  ],
  "report_current": true,
  "reseed_preserved_review": true,
  "seed_counts": {
    "document_text": 10777,
    "evaluation_result": 554,
    "forecast": 60,
    "mapping_rule": 6,
    "observation": 37,
    "parameter_set": 6,
    "parameter_set_context": 81,
    "parameter_update": 6,
    "parameter_update_observation": 6,
    "review_decision": 37,
    "run": 7,
    "scenario": 11,
    "source": 30
  }
}
```

### final replay after restart

```json
{
  "replays": [
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "1259b6e2c777488cb487f105cd403eb3697e1c0fea9f5fb19a3e8801e27eff61",
      "run_id": "cc0aa8c5-539c-5fd1-85d5-ea87bfe6175d",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "27ab77ba607d6b306ff663640f26c75328d18efd72d86f3e474099602ffe833b",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7d1a0038211fe48e5baaca8f478163fc4f189248db80dc8460f624f681b52bc7",
      "run_id": "846c4e0b-a634-5bed-996d-3785bb899846",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.3322676295501878e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "4b25be2523ca4d10556ad31fcb3eeaf7aee8b24fc0fe569e5703f8a235097b10",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "88105420099244c4504aab3641ec9ecaca8c2c6090cb8a8cce42172a72c6448a",
      "run_id": "fbbad1df-6531-4a41-86e0-32dda8a482c2",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "361799585560f720b65f7108b1d0bc4c04fd94ca7ab78ce6965a39d032ddc15f",
      "run_id": "3752b7df-c114-5fa4-b312-efe5a5908c38",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.9984014443252818e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "fa1c7bd0d747eef14b1e68ad3f8db9c5b8e789a3e86432d8dd2298361c54faea",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "98dba6f33fb6603e8f4561aeeae34ff6583af5963d2aca77099fffa82bbe075c",
      "run_id": "db0ff361-957b-5148-8299-6c71d0313f57",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 1.5543122344752192e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "5dabe0961f0d9e5d21f28647be5e6edf49246a40ef0cf44f26438cf00ef12b24",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "a9663464147616255f391896b450513809a174744df5ef360bb83aa0542bacf7",
      "run_id": "20673695-fcda-54a8-8020-3d670ee80847",
      "status": "numerically_equivalent"
    },
    {
      "differences": [
        "outputs_hash",
        "lib_versions.blas: 'accelerate' -> 'scipy-openblas'",
        "lib_versions.machine: 'arm64' -> 'aarch64'",
        "lib_versions.os: 'macOS-26.5.1-arm64-arm-64bit' -> 'Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41'",
        "lib_versions.python: '3.12.2' -> '3.12.13'",
        "lib_versions.simd: 'ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4' -> 'ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4'"
      ],
      "llm_provider": "",
      "max_relative_difference": 2.1094237467877974e-15,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "accelerate",
        "machine": "arm64",
        "numpy": "2.5.3",
        "os": "macOS-26.5.1-arm64-arm-64bit",
        "python": "3.12.2",
        "simd": "ASIMD,ASIMDDP,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "04a0ff13875572e677cd36a0694a6d616aadfe79e2b06b19e1c9b63862d13c1f",
      "run_id": "ab595be3-2964-5845-b6f3-4d8d4fce6bf3",
      "status": "numerically_equivalent"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "b7aff882278098a7712a0fc92be5762f276e9916eee40c961b1e9c8ad1eb90cb",
      "run_id": "12c847ab-f377-445f-8a8d-cc7bda139ac5",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "7c981dd2a2c520a7c0d206e72c05007b9fb424426396b2fcf9d46b5f74af348a",
      "run_id": "c2b46822-d556-4a8c-be06-ae70ea291fa4",
      "status": "exact_match"
    },
    {
      "differences": [],
      "llm_provider": "",
      "max_relative_difference": 0.0,
      "recomputed_code_version": "0.1.0+cf93263a1d638ffa",
      "recomputed_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recomputed_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "recorded_code_version": "0.1.0+cf93263a1d638ffa",
      "recorded_lib_versions": {
        "blas": "scipy-openblas",
        "machine": "aarch64",
        "numpy": "2.5.3",
        "os": "Linux-5.15.49-linuxkit-pr-aarch64-with-glibc2.41",
        "python": "3.12.13",
        "simd": "ASIMD,ASIMDDP,ASIMDFHM,ASIMDHP,FPHP,NEON,NEON_FP16,NEON_VFPV4"
      },
      "recorded_outputs_hash": "0f62b37029bc9ddd7441f40bee02880aa349f0b85a6af7d05e1176129eae3aa8",
      "run_id": "25173825-9060-4972-84f3-8e99a1e121db",
      "status": "exact_match"
    }
  ]
}
```

## Notes

- Developer stack on ports 8000/3000/55432 is not used.
- Browser evidence is recorded separately; this script verifies API flows.
- New runs require exact replay; bundled runs retain the documented 1e-9 cross-runtime tolerance.

## Browser acceptance — exported web port 13000

Playwright used a fresh browser session after the scripted restart. Console errors: 0; warnings: 0. The initial preparatory session encountered a transient connection refusal during the deliberate server restart; the final browser session began after services were healthy and had no console errors.

| Flow | Result | Evidence |
| --- | --- | --- |
| Guide and product tour | PASS | Started and finished the eight-step tour; normal navigation after a submitted run paused the tour and its skip/continue control returned to the saved example. [Guide](lon38-guide.png). |
| UF-01 starting states | PASS | Both July 23, 2024 and October 28, 2025 rendered with their cutoffs. Net revenue displayed 8,900 USD millions, FY2024Q3, GAAP; its dialog highlighted the retained 8,900 passage at characters 59493–59498 and linked the SEC original. [Source](lon38-evidence.png). |
| Evidence and review | PASS | Booking room-nights observation, original/effective values, retained passage, review history and mapping controls rendered. Reseed preservation was tested in the scripted stage. |
| UF-03 scenarios | PASS | Submitted paired runs through the actual UI: baseline `c5bc187f-2b0f-4fa4-bbc4-6bab234b37b1`, variant `8a2a2dec-5520-4946-bb66-fc7c01ce5fdf`; both succeeded with seed 22, 5,000 paths and four quarters. Inspected net revenue and operating-profit saved comparisons, path-wise differences, conditional attribution and sensitivity. [Comparison](lon38-comparison.png). |
| UF-04 valuation | PASS | Separate earnings-driven and multiple-driven uncertainty, quarterly buyback-price provenance, illustrative action rule, hold outcome and action cost components rendered. |
| UF-05 evaluation | PASS | 16 scored origins and two exclusions, target-specific sample counts, baselines and coverage displayed. The guide's report/failure-case route loaded the failure diagnosis and invalidating conditions. [Evaluation](lon38-evaluation.png). |
| Prospective registration | PASS | FY2026Q4 remains “Not yet scored”; cutoff 2026-07-28T20:05:26Z and original registration 2026-10-07T19:24:14.444045Z remain visible. |
| UF-06 replay | PASS | Clicked Replay saved run for the bundled baseline; UI explicitly showed numerical equivalence, both differing hashes, tolerance and runtime details. [Replay](lon38-replay.png). |

### Supplemental guide test

Exported data was mounted read-only at `/data` in the frontend check image, then `npm test -- src/lib/tour.test.ts` ran:

```
> longaeva-web@0.1.0 test
> vitest run --config vitest.config.ts src/lib/tour.test.ts


 RUN  v3.2.4 /app

 ✓ src/lib/tour.test.ts (8 tests) 83ms

 Test Files  1 passed (1)
      Tests  8 passed (8)
   Start at  19:14:33
   Duration  582ms (transform 108ms, setup 0ms, collect 114ms, tests 83ms, environment 0ms, prepare 105ms)
```

## Retained standalone repository

- Destination: `~/Desktop/longaeva-submission` (new directory; existing destinations are refused).
- Branch: `hackathon`; exactly one neutral initial commit; zero remotes; clean working tree.
- Initial commit: `9d1a6fc5bea6b3385cc1eedf347f33ee84b0e1cd`.
- All 526 file contents and executable modes matched the verified ZIP before initialization. No Talisman history, runtime database or artifact volume was copied.
- Canonical ZIP and checksum remain under the source package's ignored `dist/` directory. Organizer upload, hosting and timed presentation rehearsal are outside LON-38.

## Closure

- After browser checks, the temporary exported Git working tree was still clean. Every ZIP file and executable bit matched the source package.
- The task-specific verification containers, network, disposable volumes and image tags were removed successfully. Existing development stacks were not stopped or reconfigured. The temporary verification directory was then removed; the retained standalone repository and canonical ZIP remain.
- No product defects were found during final acceptance, so no owning issue required a fix or reopening. Build warnings and the existing Python deprecation warnings are retained above; they did not fail checks.
