'use client'

import { useState, useRef, DragEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'

interface ResumeUploaderProps {
  onSuccess: () => void
}

export function ResumeUploader({ onSuccess }: ResumeUploaderProps) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [setPrimary, setSetPrimary] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFile(f: File) {
    setFile(f)
    setError('')
    if (!name) setName(f.name.replace(/\.[^.]+$/, ''))
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!file) return

    setUploading(true)
    setError('')

    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', name || file.name)
    fd.append('setPrimary', String(setPrimary))

    const res = await fetch('/api/resumes', { method: 'POST', body: fd })
    const data = await res.json()

    setUploading(false)

    if (!res.ok) {
      setError(data.error ?? 'Upload failed')
    } else {
      setFile(null)
      setName('')
      setSetPrimary(false)
      onSuccess()
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Drop zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragging
            ? 'border-zinc-500 bg-[#1f1f1f]'
            : file
            ? 'border-emerald-800 bg-emerald-950/20'
            : 'border-[#2a2a2a] bg-[#111] hover:border-[#333] hover:bg-[#161616]'
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.pdf,.docx,.doc"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
        />
        {file ? (
          <div>
            <svg className="mx-auto mb-2 h-8 w-8 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-sm font-medium text-white">{file.name}</p>
            <p className="mt-0.5 text-xs text-zinc-600">{(file.size / 1024).toFixed(0)} KB · Click to change</p>
          </div>
        ) : (
          <div>
            <svg className="mx-auto mb-2 h-8 w-8 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm text-zinc-400">Drop a resume here, or <span className="text-white">click to browse</span></p>
            <p className="mt-1 text-xs text-zinc-600">.txt, .pdf, .docx · max 5MB</p>
          </div>
        )}
      </div>

      {/* Name field */}
      {file && (
        <div className="space-y-3">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Label <span className="text-zinc-600">(e.g. "Finance Focus", "Primary")</span>
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Resume name"
              required
            />
          </div>

          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={setPrimary}
              onChange={(e) => setSetPrimary(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-zinc-700 bg-[#1f1f1f] accent-emerald-500"
            />
            <span className="text-xs text-zinc-400">
              Set as primary <span className="text-zinc-600">(used by the scraper for evaluations)</span>
            </span>
          </label>
        </div>
      )}

      {error && (
        <p className="rounded-lg border border-red-900/40 bg-red-950/40 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      )}

      {file && (
        <Button type="submit" variant="primary" disabled={uploading}>
          {uploading ? <Spinner className="h-3.5 w-3.5" /> : null}
          {uploading ? 'Uploading…' : 'Upload resume'}
        </Button>
      )}
    </form>
  )
}
