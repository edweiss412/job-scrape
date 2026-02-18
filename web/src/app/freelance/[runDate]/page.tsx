import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string }>
}

export default async function FreelanceRunRedirect({ params }: Props) {
  const { runDate } = await params
  redirect(`/opportunities/freelance/${runDate}`)
}
