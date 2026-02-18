import type { Metadata } from 'next'
import './globals.css'
import { AdminFeedbackButton } from '@/components/admin/FeedbackButton'

export const metadata: Metadata = {
  title: 'Job Search Dashboard',
  description: 'AV/audio engineering job search automation',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased">
        {children}
        <AdminFeedbackButton />
      </body>
    </html>
  )
}
