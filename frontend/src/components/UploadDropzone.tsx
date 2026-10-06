import { useRef, useState, type DragEvent } from 'react'
import { Loader2, Upload } from 'lucide-react'
import { ACCEPTED_EXTENSIONS } from '../utils/vocab'
import { Button } from './Button'

type UploadDropzoneProps = {
  onFiles: (files: File[]) => void
  /** Name of the file being uploaded right now, if any. */
  uploading?: string | null
  queued?: number
}

/**
 * Drop files or choose them. The server validates everything (doc 05.3); the `accept`
 * list only narrows the picker.
 */
export function UploadDropzone({ onFiles, uploading = null, queued = 0 }: UploadDropzoneProps) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const take = (list: FileList | null) => {
    const files = list ? Array.from(list) : []
    if (files.length) onFiles(files)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    take(e.dataTransfer.files)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`flex flex-col gap-4 rounded-[var(--radius-record)] border border-dashed px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6 ${
        over ? 'border-accent-strong bg-accent/10' : 'border-rule-strong bg-panel'
      }`}
    >
      <div className="flex items-start gap-3">
        {uploading ? (
          <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden />
        ) : (
          <Upload className="mt-0.5 h-5 w-5 shrink-0 text-accent" strokeWidth={1.75} aria-hidden />
        )}
        <div aria-live="polite">
          {uploading ? (
            <>
              <p className="font-semibold text-ink">Uploading {uploading}</p>
              <p className="mt-0.5 text-[0.8125rem] text-ink-faint">
                {queued > 0 ? `${queued} more waiting` : 'Stored in the simulated S3 bucket when done'}
              </p>
            </>
          ) : (
            <>
              <p className="font-semibold text-ink">Drop files to upload</p>
              <p className="mt-0.5 text-[0.8125rem] text-ink-faint">
                PDF, Word, text, Markdown, CSV, PNG or JPEG, up to 10 MiB each
              </p>
            </>
          )}
        </div>
      </div>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS}
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          take(e.target.files)
          e.target.value = ''
        }}
      />
      <Button variant="primary" onClick={() => input.current?.click()} icon={<Upload className="h-4 w-4" aria-hidden />}>
        Choose files
      </Button>
    </div>
  )
}
