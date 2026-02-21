'use client'

import { useState, useRef, KeyboardEvent } from 'react'

interface TagInputProps {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
}

export function TagInput({ tags, onChange, placeholder }: TagInputProps) {
  const [inputVal, setInputVal] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const add = (raw: string) => {
    const value = raw.trim()
    if (value && !tags.includes(value)) {
      onChange([...tags, value])
    }
    setInputVal('')
  }

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag))

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      add(inputVal)
    } else if (e.key === 'Backspace' && !inputVal && tags.length) {
      remove(tags[tags.length - 1])
    }
  }

  return (
    <div
      className="flex flex-wrap gap-1.5 rounded-lg border border-[#2a2a2a] bg-background px-3 py-2 cursor-text min-h-10.5"
      onClick={() => inputRef.current?.focus()}
    >
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded border border-emerald-900/40 bg-emerald-950/30 px-2 py-0.5 text-xs text-emerald-400"
        >
          {tag}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); remove(tag) }}
            className="ml-0.5 text-emerald-600 hover:text-emerald-300 transition-colors leading-none"
            aria-label={`Remove ${tag}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => { if (inputVal.trim()) add(inputVal) }}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-30 bg-transparent text-xs text-white outline-none placeholder:text-zinc-700"
      />
    </div>
  )
}
