'use client'

import { useState, useRef, useEffect, KeyboardEvent } from 'react'

interface TagInputProps {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  suggestions?: string[]
}

export function TagInput({ tags, onChange, placeholder, suggestions = [] }: TagInputProps) {
  const [inputVal, setInputVal] = useState('')
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const [showSuggestions, setShowSuggestions] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Filter suggestions: match anywhere in string, exclude already-added tags
  const filtered = inputVal.trim().length > 0
    ? suggestions.filter(
        (s) =>
          s.toLowerCase().includes(inputVal.toLowerCase()) &&
          !tags.some((t) => t.toLowerCase() === s.toLowerCase())
      )
    : []

  const visible = showSuggestions && filtered.length > 0

  // Reset highlight when filtered list changes
  useEffect(() => {
    setHighlightIdx(-1)
  }, [inputVal])

  // Scroll highlighted item into view
  useEffect(() => {
    if (highlightIdx >= 0 && listRef.current) {
      const item = listRef.current.children[highlightIdx] as HTMLElement | undefined
      item?.scrollIntoView({ block: 'nearest' })
    }
  }, [highlightIdx])

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const add = (raw: string) => {
    const value = raw.trim()
    if (value && !tags.some((t) => t.toLowerCase() === value.toLowerCase())) {
      onChange([...tags, value])
    }
    setInputVal('')
    setShowSuggestions(false)
  }

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag))

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (visible && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault()
      setHighlightIdx((prev) => {
        if (e.key === 'ArrowDown') return prev < filtered.length - 1 ? prev + 1 : 0
        return prev > 0 ? prev - 1 : filtered.length - 1
      })
      return
    }

    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      if (visible && highlightIdx >= 0) {
        add(filtered[highlightIdx])
      } else {
        add(inputVal)
      }
      return
    }

    if (e.key === 'Tab' && visible && highlightIdx >= 0) {
      e.preventDefault()
      add(filtered[highlightIdx])
      return
    }

    if (e.key === 'Escape' && visible) {
      e.preventDefault()
      setShowSuggestions(false)
      return
    }

    if (e.key === 'Backspace' && !inputVal && tags.length) {
      remove(tags[tags.length - 1])
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
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
          onChange={(e) => { setInputVal(e.target.value); setShowSuggestions(true) }}
          onKeyDown={onKeyDown}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => {
            // Delay to allow click on suggestion
            setTimeout(() => {
              if (inputVal.trim()) add(inputVal)
              setShowSuggestions(false)
            }, 150)
          }}
          placeholder={tags.length === 0 ? placeholder : ''}
          className="flex-1 min-w-30 bg-transparent text-xs text-white outline-none placeholder:text-zinc-700"
          role="combobox"
          aria-expanded={visible}
          aria-autocomplete="list"
          aria-activedescendant={visible && highlightIdx >= 0 ? `tag-suggestion-${highlightIdx}` : undefined}
        />
      </div>

      {visible && (
        <ul
          ref={listRef}
          role="listbox"
          className="absolute z-50 mt-1 max-h-48 w-full overflow-auto rounded-lg border border-[#2a2a2a] bg-surface-2 py-1 shadow-xl"
        >
          {filtered.map((suggestion, i) => {
            // Highlight the matching substring
            const lower = suggestion.toLowerCase()
            const matchStart = lower.indexOf(inputVal.toLowerCase())
            const before = suggestion.slice(0, matchStart)
            const match = suggestion.slice(matchStart, matchStart + inputVal.length)
            const after = suggestion.slice(matchStart + inputVal.length)

            return (
              <li
                key={suggestion}
                id={`tag-suggestion-${i}`}
                role="option"
                aria-selected={i === highlightIdx}
                onMouseDown={(e) => { e.preventDefault(); add(suggestion) }}
                onMouseEnter={() => setHighlightIdx(i)}
                className={`cursor-pointer px-3 py-1.5 text-xs transition-colors ${
                  i === highlightIdx
                    ? 'bg-emerald-950/40 text-emerald-300'
                    : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200'
                }`}
              >
                {before}<span className="text-white font-medium">{match}</span>{after}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
