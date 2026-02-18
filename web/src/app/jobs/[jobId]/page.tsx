import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ jobId: string }>
}

export default async function JobIdRedirect({ params }: Props) {
  const { jobId } = await params
  redirect(`/opportunities/fulltime/${jobId}`)
}
