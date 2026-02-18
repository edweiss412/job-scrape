import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ runDate: string; companyId: string }>
}

export default async function CompanyRedirect({ params }: Props) {
  const { runDate, companyId } = await params
  redirect(`/opportunities/freelance/${runDate}/${companyId}`)
}
