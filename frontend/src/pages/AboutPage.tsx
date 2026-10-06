import type { ReactNode } from 'react'
import { ArrowDown } from 'lucide-react'

type Label = 'S3-SIM' | 'APP' | 'UI'

const LABELS: { id: Label; meaning: string }[] = [
  { id: 'S3-SIM', meaning: 'CloudVault’s simulation of a real Amazon S3 behavior, modeled on the AWS documentation.' },
  { id: 'APP', meaning: 'CloudVault application logic that S3 itself does not provide.' },
  { id: 'UI', meaning: 'Interface representation only.' },
]

// Implemented and tested features only (AGENTS.md rule 12), grouped by label (doc 15, AM-7).
const FEATURES: { label: Label; feature: string; detail: string }[] = [
  { label: 'S3-SIM', feature: 'Private, versioned bucket', detail: 'Versioning is always on. Objects are reachable only through an owner check or a signed link, the way Block Public Access keeps a bucket private.' },
  { label: 'S3-SIM', feature: 'Put object', detail: 'Bytes are stored with a SHA-256 checksum verified on write; the ETag is the MD5 of the bytes.' },
  { label: 'S3-SIM', feature: 'Presigned download links', detail: 'Short-lived HMAC-signed links (120 seconds by default). An altered or expired link is refused with 403 AccessDenied.' },
  { label: 'S3-SIM', feature: 'Delete markers', detail: 'Deleting adds a delete marker and keeps every version; removing the marker brings the object back.' },
  { label: 'S3-SIM', feature: 'Delete by version ID', detail: 'Permanent delete removes every version and delete marker of the key.' },
  { label: 'S3-SIM', feature: 'Copy object', detail: 'Copying a version onto the same key creates a new version. Restore and storage-class changes both use it.' },
  { label: 'S3-SIM', feature: 'Storage classes', detail: 'STANDARD, STANDARD_IA and GLACIER_IR. A copy with no class is stored as STANDARD.' },
  { label: 'S3-SIM', feature: 'Head object, metadata and tags', detail: 'The S3 Inspector reads the version ID, ETag, size, class, user metadata and tags from the simulated store.' },
  { label: 'S3-SIM', feature: 'Lifecycle rules', detail: 'Noncurrent versions expire 90 days after they become noncurrent; delete markers with nothing behind them are removed. Run as a script.' },
  { label: 'APP', feature: 'Accounts', detail: 'Login with a JWT; every document belongs to one owner, and other owners’ documents do not exist for you.' },
  { label: 'APP', feature: 'Version numbers', detail: 'v1, v2, … on top of the S3 version IDs, with the restore origin of each version.' },
  { label: 'APP', feature: 'Trash', detail: 'Lists documents whose current object is a delete marker, with restore and permanent delete.' },
  { label: 'APP', feature: 'Duplicate detection', detail: 'Uploading the same content as the current version creates nothing new.' },
  { label: 'APP', feature: 'Access log', detail: 'A download is recorded when CloudVault issues its link; S3 does not report downloads.' },
  { label: 'APP', feature: 'Storage recommendations', detail: 'CloudVault’s heuristic, not AWS Intelligent-Tiering: fixed rules over age, size, time in class and recorded downloads. Apply changes the simulated storage class.' },
  { label: 'APP', feature: 'Document processing', detail: 'Text extraction runs from a durable job queue with a background worker in the backend, in place of S3 events and Lambda. Failed or stalled jobs can be retried.' },
  { label: 'APP', feature: 'Dashboard', detail: 'Totals, bytes by class and job counts, computed from CloudVault’s records.' },
  { label: 'APP', feature: 'Storage limit', detail: 'The simulated store has a total size cap (300 MiB by default) and a 10 MiB per-file limit.' },
  { label: 'UI', feature: 'Source badges', detail: '“Live from simulated S3” marks data read from the store; “Recorded by CloudVault” marks the application’s own records.' },
  { label: 'UI', feature: 'Status labels', detail: 'Storage-class swatches, processing states, and “Stalled” for a job still pending after 10 minutes.' },
]

const NOT_INCLUDED =
  'Not part of the simulation: multipart upload, Object Lock, SSE-KMS, Glacier Flexible Retrieval and Deep Archive, replication, sharing links, and any IAM, CloudWatch or other AWS service.'

function Tag({ label }: { label: Label }) {
  const tone =
    label === 'S3-SIM'
      ? 'border-shell bg-shell text-shell-ink'
      : label === 'APP'
        ? 'border-accent-strong text-accent-strong'
        : 'border-rule-strong text-ink-muted'
  return (
    <span className={`inline-block whitespace-nowrap rounded-[var(--radius-record)] border px-1.5 py-0.5 font-mono text-xs font-semibold ${tone}`}>
      [{label}]
    </span>
  )
}

function Box({ title, note, children }: { title: string; note: string; children?: ReactNode }) {
  return (
    <div className="record px-5 py-4 sm:px-6">
      <p className="font-semibold text-ink">{title}</p>
      <p className="mt-1 text-sm text-ink-muted">{note}</p>
      {children}
    </div>
  )
}

function Connector({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-2 pl-6 text-[0.8125rem] text-ink-faint">
      <ArrowDown className="h-4 w-4 shrink-0" aria-hidden />
      {label}
    </div>
  )
}

/** Doc 06.5 About: what CloudVault simulates, how it is built, and the label table (AM-7). Static. */
export function AboutPage() {
  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="text-[2.125rem] font-semibold leading-tight tracking-tight text-ink">About CloudVault</h1>
        <p className="mt-3 max-w-[68ch] text-[1.0625rem] leading-relaxed text-ink">
          <strong className="font-semibold">CloudVault is a functional simulation of Amazon S3.</strong> It reproduces
          selected S3 concepts and semantics locally, using simulated object storage kept in PostgreSQL. A real AWS
          account is not required, and nothing in CloudVault connects to or changes one.
        </p>
      </div>

      <section aria-labelledby="architecture" className="flex flex-col gap-4">
        <h2 id="architecture" className="text-xl font-semibold text-ink">Architecture</h2>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] lg:items-start">
          <div aria-label="Architecture diagram" role="group">
            <Box title="Browser: React app" note="Holds only a login token (JWT) and short-lived signed download links. No storage secrets." />
            <Connector label="HTTPS with the JWT; downloads follow a signed link" />
            <Box
              title="FastAPI backend"
              note="Accounts, documents, versions, recommendations and the dashboard. Serves signed downloads at its own simulated S3 route and runs the processing worker."
            />
            <Connector label="Short transactions; never held open across a storage call" />
            <div className="record px-5 py-4 sm:px-6">
              <p className="font-semibold text-ink">PostgreSQL</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="border border-rule px-4 py-3">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">Application tables <Tag label="APP" /></p>
                  <p className="mt-1 text-[0.8125rem] text-ink-muted">Users, documents, versions, access log, recommendations, processing jobs.</p>
                </div>
                <div className="border border-rule px-4 py-3">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">Simulated S3 store <Tag label="S3-SIM" /></p>
                  <p className="mt-1 text-[0.8125rem] text-ink-muted">One private bucket: object versions, delete markers, bytes, metadata, tags, storage class.</p>
                </div>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-3 text-sm leading-relaxed text-ink-muted">
            <p>
              The backend talks to storage only through an object-storage interface. Its one implementation is the
              simulated store, so the application code is written the way it would be against S3.
            </p>
            <p>
              Each change goes pending, then to storage, then becomes available or failed; per-document locks keep
              concurrent uploads, deletes and restores in order.
            </p>
            <p>
              Uploads are processed in memory and never written to local disk. Filenames you choose never become
              object keys.
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="labels" className="flex flex-col gap-4">
        <h2 id="labels" className="text-xl font-semibold text-ink">What is simulated, and what is CloudVault&apos;s own</h2>
        <dl className="record divide-y divide-rule">
          {LABELS.map((l) => (
            <div key={l.id} className="flex flex-col gap-1.5 px-5 py-3 sm:flex-row sm:items-baseline sm:gap-6 sm:px-6">
              <dt className="sm:w-28 sm:shrink-0"><Tag label={l.id} /></dt>
              <dd className="text-sm text-ink">{l.meaning}</dd>
            </div>
          ))}
        </dl>

        <div className="record">
          <table className="hidden w-full text-sm md:table">
            <caption className="sr-only">CloudVault features and their labels</caption>
            <thead>
              <tr className="border-b border-rule text-left">
                <th scope="col" className="caption w-28 px-6 py-2.5 font-semibold">Label</th>
                <th scope="col" className="caption w-56 px-3 py-2.5 font-semibold">Feature</th>
                <th scope="col" className="caption px-3 py-2.5 pr-6 font-semibold">How CloudVault does it</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {FEATURES.map((f) => (
                <tr key={f.feature} className="align-top">
                  <td className="px-6 py-3"><Tag label={f.label} /></td>
                  <th scope="row" className="px-3 py-3 text-left font-medium text-ink">{f.feature}</th>
                  <td className="px-3 py-3 pr-6 text-ink-muted">{f.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y divide-rule md:hidden" aria-label="CloudVault features and their labels">
            {FEATURES.map((f) => (
              <li key={f.feature} className="px-5 py-3.5">
                <p className="flex flex-wrap items-center gap-2 font-medium text-ink">
                  <Tag label={f.label} />
                  {f.feature}
                </p>
                <p className="mt-1 text-sm text-ink-muted">{f.detail}</p>
              </li>
            ))}
          </ul>
        </div>
        <p className="max-w-[72ch] text-sm text-ink-muted">{NOT_INCLUDED}</p>
      </section>
    </div>
  )
}
