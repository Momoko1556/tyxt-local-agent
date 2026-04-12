import type { ResourcePartitionId } from '../core/types';

export const PARTITION_COLORS: Record<ResourcePartitionId, number> = {
  document: 0x81a8ff,
  images: 0xffc17a,
  memory: 0xa58aff,
  skills: 0x7ce6c7,
  gateway: 0x59d0ff,
  log: 0xff8aa5,
  mcp: 0x5fe3ff,
  schedule: 0xf4d06f,
  alarm: 0xff6978,
  agent: 0x98f59d,
  task_queues: 0xffb16b,
  break_room: 0xbec6db
};

export const PARTITION_CSS_COLORS = Object.fromEntries(
  Object.entries(PARTITION_COLORS).map(([resourceId, color]) => [resourceId, `#${color.toString(16).padStart(6, '0')}`])
) as Record<ResourcePartitionId, string>;
