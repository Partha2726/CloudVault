import type { QueryClient } from '@tanstack/react-query'

/** After any change to a document: its tabs, the documents list and the dashboard refetch (doc 06.4). */
export function refreshDocument(queryClient: QueryClient, documentId: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ['document', documentId] }),
    queryClient.invalidateQueries({ queryKey: ['documents'] }),
    queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  ])
}
