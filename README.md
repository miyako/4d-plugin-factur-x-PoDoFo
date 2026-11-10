# 4d-plugin-factur-x-PoDoFo

Embed a Factur-X / ZUGFeRD invoice into a PDF/A-3 document from 4D.

The plugin takes an existing PDF/A document, an invoice XML file and any number
of supplementary attachments, and writes a new document in which every file is
registered both in `/Names/EmbeddedFiles` and in the catalog's `/AF` array, with
the XMP packet extended with the Factur-X description and its PDF/A extension
schema. The backend is [PoDoFo](https://github.com/podofo/podofo), statically
linked, so the plugin has no runtime dependencies.

The command is API-compatible with
[4d-plugin-factur-x-QPDF](https://github.com/miyako/4d-plugin-factur-x-QPDF):
same command name, same parameters, same error codes, same constants. Only the
PDF backend differs, so the two plugins can be swapped without touching 4D code.
They cannot be installed side by side, because 4D refuses to load two plugins
that declare the same name.

## Requirements

- 4D v21.1 or later (matching `compatibilityVersion` `2101` in the test project)
- macOS (universal) or Windows x64

## Installation

Download the latest release from the [Releases](../../releases) page.

1. Extract the `.zip` (or mount the notarized `.dmg` on macOS) to get
   `facturx.bundle`
2. Copy it into your 4D application's or database's **Plugins** folder
3. Restart 4D

The bundle contains both the macOS and Windows binaries, so a single copy works
on either platform.

## Command

### `PDFA Embed FacturX`

```4d
$status:=PDFA Embed FacturX($pdfPathIn; $xmlInfo; $pdfPathOut; $attachments; $options)
```

| Parameter | Type | Description |
|---|---|---|
| `$pdfPathIn` | Text | POSIX path of the source PDF. Required. |
| `$xmlInfo` | Object | Invoice XML descriptor. Required. |
| `$pdfPathOut` | Text | POSIX path of the document to write. Required. May be the same file as `$pdfPathIn`. |
| `$attachments` | Collection | Supplementary files. Optional, may be `Null`. |
| `$options` | Object | Behaviour switches. Optional, may be `Null`. |
| `$status` | Object | Outcome. Never `Null`. |

Paths are POSIX paths on both platforms. Convert 4D paths with
`Convert path system to POSIX` or use `File(...).path`.

#### `$xmlInfo`

| Property | Type | Default | Description |
|---|---|---|---|
| `path` | Text | — | POSIX path of the invoice XML. Required. |
| `name` | Text | `"factur-x.xml"` | File name recorded in the PDF. Must end in `.xml` and contain no path separator. |
| `relationship` | Text | `"Alternative"` | `/AFRelationship`. Only `"Alternative"` or `"Source"` are accepted. |
| `description` | Text | `"Factur-X Invoice"` | `/Desc` on the file specification. |
| `documentType` | Text | `"INVOICE"` | `fx:DocumentType`. One of `INVOICE`, `CREDITNOTE`, `ORDER`, `ORDER_RESPONSE`, `DESPATCH_ADVICE`. |
| `version` | Text | — | `fx:Version`, e.g. `"1.0"`. Required. |
| `conformanceLevel` | Text | — | `fx:ConformanceLevel`, e.g. `"EN 16931"`. Required. |
| `xmpPrefix` | Text | derived from `name` | Overrides the XMP prefix (`fx` or `zf`). |
| `xmpNamespace` | Text | derived from `name` | Overrides the XMP namespace URI. |

The XML must be a valid UTF-8 byte sequence. A UTF-8 BOM is stripped and
reported as a warning rather than rejected.

#### `$attachments`

A collection of objects:

| Property | Type | Default | Description |
|---|---|---|---|
| `path` | Text | — | POSIX path of the file. Required. |
| `name` | Text | — | File name recorded in the PDF. Required, no path separator, must be unique. |
| `type` | Text | — | MIME type, e.g. `"text/plain"`. Required. |
| `relationship` | Text | `"Unspecified"` | `/AFRelationship`. `"Alternative"` and `"Source"` are reserved for the invoice. |
| `description` | Text | `""` | `/Desc` on the file specification. |

#### `$options`

| Property | Type | Default | Description |
|---|---|---|---|
| `overwrite` | Boolean | `False` | Allow writing over an existing `pdfPathOut`. Required for in-place editing. |
| `strict` | Boolean | `False` | Turn the pre-flight PDF/A warnings into errors. |
| `forcePdfAPart3` | Boolean | `False` | Rewrite `pdfaid:part` to `3` instead of only warning. |

#### `$status`

| Property | Type | Description |
|---|---|---|
| `success` | Boolean | True only when `errorCode` is `0`. |
| `errorCode` | Integer | See the table below. |
| `errorMessage` | Text | Human-readable detail. Empty on success. |
| `warnings` | Collection | Text messages. Always present, possibly empty. |

The status object is the only error channel: the command never raises a 4D
error and never lets a C++ exception escape.

### Example

```4d
var $xmlInfo; $status : Object
var $resources; $in; $out : Text

$resources:=Convert path system to POSIX(Get 4D folder(Current resources folder))
$in:=$resources+"invoice.pdf"
$out:=$resources+"invoice-facturx.pdf"

$xmlInfo:=New object
$xmlInfo.path:=$resources+"factur-x.xml"
$xmlInfo.documentType:="INVOICE"
$xmlInfo.version:="1.0"
$xmlInfo.conformanceLevel:="EN 16931"

$status:=PDFA Embed FacturX($in; $xmlInfo; $out; New collection(New object(\
"path"; $resources+"terms.txt"; "name"; "terms.txt"; "type"; "text/plain"; \
"relationship"; "Supplement")); New object("overwrite"; True))

If (Not($status.success))
	ALERT(String($status.errorCode)+": "+$status.errorMessage)
End if
```

## Error codes

Every code has a matching 4D constant in the **Factur-X** theme, so you can
compare against a name instead of a number.

| Code | Constant | Meaning |
|---|---|---|
| 0 | `facturx ok` | Success |
| 100 | `facturx error bad arity` | Wrong number of parameters |
| 101 | `facturx error input path empty` | `pdfPathIn` empty |
| 102 | `facturx error input pdf unreadable` | `pdfPathIn` cannot be opened |
| 103 | `facturx error xmlinfo not object` | `xmlInfo` is not an object |
| 104 | `facturx error xml path missing` | `xmlInfo.path` missing |
| 105 | `facturx error xml unreadable` | `xmlInfo.path` cannot be read |
| 106 | `facturx error xml empty` | Invoice XML is empty |
| 107 | `facturx error xml not utf8` | Invoice XML is not valid UTF-8 |
| 108 | `facturx error xml name invalid` | `xmlInfo.name` invalid |
| 109 | `facturx error xml relationship invalid` | `xmlInfo.relationship` invalid |
| 110 | `facturx error xml document type invalid` | `xmlInfo.documentType` invalid |
| 111 | `facturx error xml version missing` | `xmlInfo.version` missing |
| 112 | `facturx error xml conformance missing` | `xmlInfo.conformanceLevel` missing |
| 113 | `facturx error output path empty` | `pdfPathOut` empty |
| 114 | `facturx error attachments not collection` | `attachments` is not a collection |
| 115 | `facturx error attachment not object` | A collection element is not an object |
| 116 | `facturx error attachment unreadable` | Attachment cannot be read |
| 117 | `facturx error attachment name invalid` | Attachment name invalid |
| 118 | `facturx error attachment name duplicate` | Attachment name used twice |
| 119 | `facturx error attachment type invalid` | Attachment MIME type malformed |
| 120 | `facturx error attachment relationship invalid` | Attachment relationship invalid |
| 121 | `facturx error options not object` | `options` is not an object |
| 122 | `facturx error property wrong type` | A property has the wrong 4D type |
| 201 | `facturx error pdf parse failed` | Source PDF could not be parsed |
| 202 | `facturx error pdf encrypted` | Source PDF is encrypted |
| 203 | `facturx error pdf already facturx` | Source PDF already carries an invoice |
| 204 | `facturx error pdf no xmp` | Source PDF has no XMP metadata |
| 205 | `facturx error pdf version too old` | Source PDF predates 1.7 (`strict`) |
| 206 | `facturx error pdf name collision` | Attachment name already embedded |
| 207 | `facturx error pdf not pdfa3` | Source PDF is not PDF/A-3 (`strict`) |
| 301 | `facturx error output exists` | Output exists and `overwrite` is not set |
| 302 | `facturx error output dir unwritable` | Output directory not writable |
| 303 | `facturx error output temp failed` | Temporary file could not be created |
| 304 | `facturx error output rename failed` | Temporary file could not be renamed |
| 305 | `facturx error output inplace no overwrite` | In-place edit without `overwrite` |
| 401 | `facturx error backend` | PoDoFo error or failed native object-property / attachment-element read (includes the 4D error code) |
| 402 | `facturx error unexpected exception` | Unexpected C++ exception |
| 403 | `facturx error unknown fatal` | Unknown fatal condition |

## Behaviour notes

- **Atomic output.** The document is written to a temporary file in the target
  directory and renamed into place only after a complete, successful write, so
  a failure never leaves a truncated file behind.
- **In-place editing.** `pdfPathOut` may be the same file as `pdfPathIn`; this
  requires `options.overwrite`. The source is closed only after the temporary
  file has been fully written.
- **Re-run protection.** If the source already embeds an invoice, or its XMP
  already declares the target Factur-X namespace, the command fails with 203
  rather than producing a document with two conflicting invoices.
- **XMP is extended, not replaced.** Existing descriptions, including
  `pdfaid:part`, are preserved, and the PDF/A extension schema is merged into
  an existing `pdfaExtension:schemas` bag when one is present.
- **Streams are preserved.** The document is saved with
  `PdfSaveOptions::NoFlateCompress`, so existing streams are not recompressed,
  embedded payloads round-trip byte for byte, and the metadata stream stays
  unfiltered as PDF/A requires. `PdfSaveOptions::NoMetadataUpdate` keeps PoDoFo
  from regenerating `/Catalog/Metadata` over the hand-built XMP packet.
- **Verified output.** The document produced from the test project's PDF/A-3
  fixture validates as PDF/A-3B with [veraPDF](https://verapdf.org/):
  146 rules passed, 0 failed.

## Building from source

### Prerequisites

- CMake 3.20+
- Xcode command line tools (macOS) or Visual Studio 2022+ (Windows)
- PoDoFo 1.x

The build resolves PoDoFo through `find_package(podofo CONFIG)` first and falls
back to `pkg-config`, so either a Homebrew or a vcpkg installation works:

```bash
brew install podofo                              # macOS, quickest for development
vcpkg install podofo:x64-windows-static          # Windows
```

Homebrew ships PoDoFo as an arm64-only dynamic library, which is fine for
building and running the tests locally but cannot produce the universal, self
contained bundle that is published. Release builds therefore use vcpkg static
libraries; see `vcpkg.json` and `triplets/`.

### Clone

```bash
git clone --recurse-submodules https://github.com/miyako/4d-plugin-factur-x-PoDoFo.git
cd 4d-plugin-factur-x-PoDoFo
```

### Build (macOS)

```bash
cd facturx
cmake -S . -B cmake-build -DCMAKE_BUILD_TYPE=Release
cmake --build cmake-build --parallel
```

PoDoFo and its dependencies cannot configure for more than one architecture at
a time, so a universal binary is produced by building `arm64` and `x86_64`
separately, each against its own vcpkg triplet, and merging them with `lipo`.
See `.github/workflows/release.yml`.

### Build (Windows)

```pwsh
cd facturx
cmake -S . -B cmake-build -A x64 `
  -DCMAKE_TOOLCHAIN_FILE="$env:VCPKG_INSTALLATION_ROOT/scripts/buildsystems/vcpkg.cmake" `
  -DVCPKG_TARGET_TRIPLET=x64-windows-static
cmake --build cmake-build --config Release --parallel
```

`x64-windows-static` is used so that PoDoFo and the C runtime are both linked
statically, matching the `/MT` setting of the plugin target.

### Run the tests

Requires [tool4d](https://developer.4d.com/docs/Admin/cli/), which is free and
needs no licence:

```bash
/path/to/tool4d --dataless --startup-method=test_all \
  --project="$(pwd)/facturx/facturx-test/Project/facturx.4DProject"
```

The suite prints `PASS` on success.

The conformance test is skipped unless `facturx-test/Resources/pdfa3.pdf`
exists. Generate it with Ghostscript, then validate the plugin's output with
[veraPDF](https://verapdf.org/):

```bash
./facturx/make-pdfa3.sh
# run the suite, then:
verapdf --flavour 3b facturx/facturx-test/conformance-out.pdf
```

Ghostscript and veraPDF are build-time tools only; neither is linked into the
plugin.

### Native ownership regression (macOS)

With the pinned SDK submodule, Xcode command-line tools, Python 3, pkg-config
and PoDoFo available, run from the repository root:

```bash
python3 tests/native/run.py
```

This compiles the actual production translation unit and the **complete,
unchanged** bundled SDK against an engine-boundary host shim, without building
a plugin bundle or invoking release scripts. ASan/UBSan and explicit
string/handle/reference balances cover failed getter outputs before ownership
adoption, successful and mismatched getter cleanup, exact ASCII/BMP/supplementary
UTF-16 lengths and terminators, allocated/null empty strings, synchronous setter
copies, independent warning values, object/collection return handoffs, and SDK
array transfer/replacement/shrink/rejection contracts. `--source-root PATH`
runs the same harness against another extracted source tree and its pinned SDK.

The ownership audit covers all first-party native sources and headers
(`facturx-4dplugin.cpp` / `.h`), including internal helpers, plus CMake include /
compile reachability, `manifest.json` and the actual `PluginMain` /
`FourDPackex` exports (`facturx.def` on Windows). There is one command, selector 1,
and no separate dormant native wrapper, picture, pointer or callback family.
The SDK is the `4d/4D-Plugin-SDK` submodule at
`cd97d1876d4258b56d2516e8ad2816f4ee93e0b5`; its `rev: v14` comment is not an
upstream release identity. Successful property/element values are cleared after
use; input parameters remain borrowed; synchronous setter inputs are released
after the engine copies them; status and warning collection handoffs stay owning.

The shim is not a real 4D host or Windows crash reproduction. LeakSanitizer is
unavailable on macOS, so explicit allocation/reference balances supplement
ASan/UBSan. SDK internals and third-party libraries are not patched or certified:
in particular, the SDK collection-length getter's own failed-output/error
handling and array resize-OOM behavior remain outside this bounded fix.

## CI/CD

| Workflow | Trigger | Purpose |
|---|---|---|
| `test.yml` | Push / PR / manual | Build and test on macOS + Windows, validate with veraPDF |
| `bump-version.yml` (Bump version) | Manual, patch/minor/major | Commit coordinated source version metadata to the selected branch only; no tags or automatic Build |
| `release.yml` (Build) | Manual, no inputs (branch selector only) | Build the selected commit on both platforms, sign, notarize, then create a new tag and release |

Run **Bump version** on the desired branch, then separately run **Build** on
that branch. Build checks out the dispatch's immutable `github.sha` in every
job, not a moving branch or a pre-existing tag. It accepts any selected branch;
there is no main-only publication restriction.

`VERSION` is authoritative and must be strict `X.Y.Z` without leading zeros.
`facturx/Version.cmake` reads it into `FACTURX_VERSION`; both bundle version
properties reference that variable, and `Info.plist.in` retains its CMake
placeholders. Literal source versions, if introduced, must agree and are
updated together by Bump version. The migration repairs the old `1.0` bundle
metadata to resolve to the existing `VERSION`, without incrementing it.
The vcpkg manifest's package version, dependency versions, and 4D format
compatibility version are independent and are not bumped.

Bump version pushes only the selected branch without force or followed tags.
A concurrent branch advance rejects the push; rerun from the new branch tip.
Build rejects existing remote tags or releases (including drafts), metadata
drift, and remote/API errors before building, and rechecks immediately before
publication. Builds are serialized across branches. Only after both platform
builds, universal-binary and bundle-version checks, signing, accepted ZIP/DMG
notarization and DMG stapling/validation succeed does it push `vX.Y.Z`
non-forcibly at the exact selected SHA and create a **new** release with
`facturx-X.Y.Z.zip` and `facturx-X.Y.Z.dmg`. No tag, release or asset is
overwritten or deleted. A create-only API call publishes a non-draft,
non-prerelease release, followed by `gh release upload` without `--clobber`.
The original policy of no generated release notes is retained.
`gh release create` with assets is avoided because it deletes its draft on
upload failure.

Publication is not atomic: a failure after the tag push can leave a tag,
or a release with incomplete assets. Build deliberately refuses to overwrite
that state on rerun. Inspect the failed run and reconcile it manually before
choosing a new version. The independent Build and Test workflow remains
push/PR/manual CI; it does not publish releases.

Lifecycle regressions use only local fixtures and mocked publication services:

```bash
python3 -m unittest discover -s .github/scripts -p 'test_*.py'
actionlint
```

### Required secrets (`release.yml` only)

| Secret | Description |
|---|---|
| `APPLE_DEVELOPER_ID_CERTIFICATE` | Base64-encoded `.p12` Developer ID Application certificate |
| `APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD` | Password for the `.p12` export |
| `KEYCHAIN_PASSWORD` | Arbitrary password for the runner's temporary keychain |
| `NOTARYTOOL_APPLE_ID` | Apple ID email for notarization |
| `NOTARYTOOL_TEAM_ID` | Apple Developer Team ID |
| `NOTARYTOOL_PASSWORD` | App-specific password from appleid.apple.com |

## Third-party components

| Component | Licence | Linkage |
|---|---|---|
| [PoDoFo](https://github.com/podofo/podofo) | LGPL-2.0-or-later **OR** MPL-2.0 | Static |
| [4D Plugin SDK](https://github.com/4d/4D-Plugin-SDK) | 4D | Static |

PoDoFo pulls in zlib, freetype, libxml2 and OpenSSL through vcpkg; all of those
are permissively licensed.

### A note on the PoDoFo licence

PoDoFo is dual-licensed **LGPL-2.0-or-later OR MPL-2.0**, which is a weaker
static-linking story than the Apache-2.0 backend of the qpdf variant and is
worth a deliberate decision before shipping a closed-source product:

- Under the **MPL-2.0** arm, static linking into proprietary software is
  permitted provided that modifications to PoDoFo's *own* files are published.
  This plugin does not modify PoDoFo, so distributing the statically linked
  bundle alongside the PoDoFo source or a link to it satisfies the obligation.
- Under the **LGPL** arm, static linking additionally requires giving
  recipients the means to relink against a modified PoDoFo.

If the licence terms are unacceptable, use
[4d-plugin-factur-x-QPDF](https://github.com/miyako/4d-plugin-factur-x-QPDF)
instead: it is API-identical and Apache-2.0 throughout.

## License

See [LICENSE](LICENSE).
