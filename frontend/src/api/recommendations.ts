import { api } from './client'
import type { Recommendation, RecommendationStatus } from './types'

/** Every recommendation query sits under ['recommendations'], so one invalidation refreshes all views. */
export const recommendationKeys = {
  all: ['recommendations'] as const,
  list: (status: RecommendationStatus) => ['recommendations', status] as const,
}

export function listRecommendations(status: RecommendationStatus) {
  return api<{ items: Recommendation[] }>('/recommendations', { query: { status: status.toLowerCase() } })
}

/** W10: the backend re-runs CloudVault's heuristic; nothing is calculated in the browser. */
export function refreshRecommendations() {
  return api<{ items: Recommendation[] }>('/recommendations/refresh', { method: 'POST' })
}

/** W11: the backend changes the simulated storage class. Already APPLIED returns 200 unchanged. */
export function applyRecommendation(id: string) {
  return api<Recommendation>(`/recommendations/${id}/apply`, { method: 'POST' })
}

export function dismissRecommendation(id: string) {
  return api<Recommendation>(`/recommendations/${id}/dismiss`, { method: 'POST' })
}
