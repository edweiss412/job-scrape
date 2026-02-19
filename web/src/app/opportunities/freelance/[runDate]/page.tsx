import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string }>
}

export default async function FreelanceRunPage({ params }: Props) {
  const { runDate } = await params
  redirect(`/opportunities/freelance?run=${runDate}`)
}
