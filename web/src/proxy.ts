import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'
import { ADMIN_EMAIL } from '@/lib/admin'

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
          response = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          )
        },
      },
    },
  )

  const { data: { user } } = await supabase.auth.getUser()
  const { pathname } = request.nextUrl

  // DEV BYPASS: skip auth when NEXT_PUBLIC_SKIP_AUTH=true (local testing only)
  if (process.env.NEXT_PUBLIC_SKIP_AUTH === 'true') {
    return response
  }

  const isPublic = pathname === '/login' || pathname.startsWith('/api/auth')

  if (isPublic) {
    // Redirect already-authenticated users away from login
    if (user && pathname === '/login') {
      return NextResponse.redirect(new URL('/opportunities/fulltime', request.url))
    }
    return response
  }

  // Require auth for everything else
  if (!user) {
    const url = new URL('/login', request.url)
    url.searchParams.set('next', pathname)
    return NextResponse.redirect(url)
  }

  // Admin-only routes
  if (pathname.startsWith('/admin') && user.email !== ADMIN_EMAIL) {
    return NextResponse.redirect(new URL('/opportunities/fulltime', request.url))
  }

  return response
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
