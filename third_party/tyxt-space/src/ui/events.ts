import type { GrowthState } from '../core/types';

export const EVENTS = {
  growthUpdated: 'growth-updated',
  cycleTheme: 'cycle-theme'
} as const;

export type UiEvents = {
  [EVENTS.growthUpdated]: GrowthState;
};