import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string }>
}

export default async function RunDateRedirect({ params }: Props) {
  const { runDate } = await params
  redirect(`/opportunities/fulltime?run=${runDate}`)
}
