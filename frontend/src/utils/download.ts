import type { QueryClient } from '@tanstack/react-query'
import { getDownloadLink } from '../api/documents'

/**
 * W3: ask for a signed, version-bound link and let the browser navigate to it. The link is
 * the credential; object bytes never pass through React. The access log grows, so the
 * document's queries and the dashboard are refreshed.
 */
export async function startDownload(queryClient: QueryClient, documentId: string, version?: number) {
  const { url } = await getDownloadLink(documentId, version)
  window.location.assign(url)
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['document', documentId] }),
    queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  ])
}
