import { cn } from '@/lib/utils'
import { InputHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode
}

export function Input({ icon, className, ...props }: InputProps) {
  if (icon) {
    return (
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
          {icon}
        </div>
        <input
          className={cn(
            'block w-full rounded-lg border border-[#1f1f1f] bg-[#111] pl-9 pr-3 py-2 text-sm text-zinc-200',
            'placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600',
            className,
          )}
          {...props}
        />
      </div>
    )
  }

  return (
    <input
      className={cn(
        'block w-full rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-2 text-sm text-zinc-200',
        'placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600',
        className,
      )}
      {...props}
    />
  )
}
