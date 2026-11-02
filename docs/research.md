# Research library

Research is available at `/research` in Core navigation. Administrators can upload, categorize, reprocess and delete research; authenticated workspace readers can search, read and download it. The four categories are Equity Strategy, Credit Strategy, Economic, and Industry & Thematic. Omitting the category enables automatic classification. A manual selection always takes precedence, including changes made while processing runs.

## Upload and conversion

Accept native and scanned PDFs up to 30 MiB and 200 pages. Reject malformed or password-protected documents with an actionable error. Identical bytes open the existing report without starting a second job or changing its category. Original files remain private and available while processing continues after navigation or refresh.

`research_conversion` is a registered durable job using the existing async runner. Its stages are queued, reading, condensing and checking; terminal states are ready, needs_review and failed. The configured mid-tier provider/model and prompt version are recorded per revision. The owned Talisman text endpoint is not PDF-capable; select a PDF-capable provider in AI Settings. No external web search is used for conversion.

The versioned prompt in `api/research_prompts.py` preserves the approved conversion instructions. Four-page batches include both the native PDF and explicit rendered page images, allowing OCR and visual inspection. Extraction tracks original page numbers, ordered heading/text/visual blocks and author/metadata evidence. Large sections are processed in bounded groups and reconciled. Each section retains its exact heading and hierarchy, a cohesive condensed paragraph, and descriptions of all substantive visuals with captions and sources.

A separate source comparison checks every page, metadata, headings/order, numerical facts, figures and qualifications. Missing page coverage triggers smaller checks. There is one source-directed repair pass; unresolved issues enter needs_review without publishing or indexing the attempted revision. Limits of 350 model calls and 70 minutes bound a conversion attempt; the queue timeout is 80 minutes. Long reports may require splitting. Model checks reduce errors but cannot guarantee fidelity on every publisher layout or illegible scan.

Verified output is an actual UTF-8 `.md` download named from the original report title, with only filesystem-unsafe characters replaced. Missing metadata is omitted, never derived from the filename. Reprocessing retains the last verified content and metadata until a new revision passes. Markdown is rendered without embedded images or HTML.

## Persistence and retrieval

Canonical metadata is stored in the existing temporal `DocumentArtifact` object with `document_type=research_report`, alongside transactional provenance events. Originals, extraction, sections, validation evidence and Markdown revisions live under private `live/research/<content-sha256>/` blob keys. No new database schema or environment secret is required; the deployment includes the pinned PDFium dependency.

Per-report Postgres advisory locks serialize uploads, publication, category changes, indexing and deletion. Attempt tokens fence superseded workers. Indexing uses the same database transaction as its state update. Deletion commits its tombstone and search removal before deleting nontransactional blobs, so a cleanup failure cannot resurrect content. Repeating DELETE safely retries cleanup. A concurrent identical reupload is protected by the same report lock.

A separate retryable `research_index` job indexes both the condensed Markdown and page-labelled source extraction into the existing Postgres full-text retrieval tables. Library content filtering collects distinct matching documents before pagination. Stan gets `search_research` and paginated `read_research_report`, with report metadata, section/original-page links and private-source instructions. General knowledge-base search also includes research. Revision checks exclude stale index hits. OCR passages are labelled as extracted source text; condensed passages are paraphrases, not verbatim quotations. The PDF remains the authority for exact quotations.

## Operations and validation

Use Retry processing for failed/interrupted conversion, Reprocess for a new revision, or Retry search indexing when Markdown is ready but indexing failed. The UI reconciles failed/cancelled jobs and missing job records. Check the existing job/provenance logs for infrastructure failures; never log PDF bodies or provider credentials. A needs_review report exposes the source-check findings and original PDF for correction/retry.

Automated coverage includes real PDF parsing, all four categories, manual overrides during processing, deduplication, incomplete/illegible/truncated responses, page coverage, preservation of previous revisions, auth/roles, deletion cleanup failure and worker fencing. `tests/test_research_postgres.py` runs isolated real transactions, concurrent uploads, full-text retrieval, page citations and deletion when `TEST_RESEARCH_POSTGRES_URL` points to a disposable Postgres database with pgvector.

Initial live evaluation used four synthetic two-page reports, one per category, including an image-only scanned credit report, charts, tables, author metadata, sources, risks and appendices. All four passed conversion and category checks. Browser checks cover the reader, manual category editing, actual Markdown download, PDF upload, processing after refresh and mobile layout. These synthetic checks are a release baseline; additional publisher layouts should be added as representative private fixtures become available.
