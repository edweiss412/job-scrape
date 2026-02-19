'use client'

import { useState } from 'react'

interface CompanyLogoProps {
  logoUrl: string | null
  website: string | null
  name: string
  size?: number
}

function getFaviconUrl(website: string): string {
  try {
    const domain = new URL(website).hostname
    return `https://www.google.com/s2/favicons?domain=${domain}&sz=128`
  } catch {
    return ''
  }
}

function getInitial(name: string): string {
  return name.charAt(0).toUpperCase()
}

export function CompanyLogo({ logoUrl, website, name, size = 32 }: CompanyLogoProps) {
  const [src, setSrc] = useState<string | null>(
    logoUrl || (website ? getFaviconUrl(website) : null)
  )
  const [errored, setErrored] = useState(false)

  if (!src || errored) {
    return (
      <div
        className="flex shrink-0 items-center justify-center rounded-md border border-[#2a2a2a] bg-[#1a1a1a]"
        style={{ width: size, height: size }}
      >
        <span
          className="font-mono font-bold text-zinc-600 select-none"
          style={{ fontSize: size * 0.4 }}
        >
          {getInitial(name)}
        </span>
      </div>
    )
  }

  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      className="shrink-0 rounded-md border border-[#2a2a2a] bg-[#1a1a1a] object-contain"
      onError={() => {
        // If we were showing logo_url, try favicon fallback
        if (src === logoUrl && website) {
          const fallback = getFaviconUrl(website)
          if (fallback) {
            setSrc(fallback)
            return
          }
        }
        setErrored(true)
      }}
    />
  )
}
