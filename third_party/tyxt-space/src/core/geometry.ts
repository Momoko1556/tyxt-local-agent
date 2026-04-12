import type { Point } from './types';

export function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
    const current = polygon[index];
    const last = polygon[previous];

    const intersect =
      current.y > point.y !== last.y > point.y &&
      point.x < ((last.x - current.x) * (point.y - current.y)) / (last.y - current.y + Number.EPSILON) + current.x;

    if (intersect) {
      inside = !inside;
    }
  }

  return inside;
}

export function distanceSquared(a: Point, b: Point): number {
  const offsetX = a.x - b.x;
  const offsetY = a.y - b.y;
  return offsetX * offsetX + offsetY * offsetY;
}

export function nearestPoint(points: Point[], target: Point): Point {
  let bestPoint = points[0];
  let bestDistance = distanceSquared(bestPoint, target);

  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const candidateDistance = distanceSquared(point, target);
    if (candidateDistance < bestDistance) {
      bestPoint = point;
      bestDistance = candidateDistance;
    }
  }

  return bestPoint;
}

function orientation(a: Point, b: Point, c: Point): number {
  return (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
}

function onSegment(a: Point, b: Point, c: Point): boolean {
  return c.x <= Math.max(a.x, b.x) && c.x >= Math.min(a.x, b.x) && c.y <= Math.max(a.y, b.y) && c.y >= Math.min(a.y, b.y);
}

export function segmentsIntersect(startA: Point, endA: Point, startB: Point, endB: Point): boolean {
  const o1 = orientation(startA, endA, startB);
  const o2 = orientation(startA, endA, endB);
  const o3 = orientation(startB, endB, startA);
  const o4 = orientation(startB, endB, endA);

  if (o1 * o2 < 0 && o3 * o4 < 0) {
    return true;
  }

  if (o1 === 0 && onSegment(startA, endA, startB)) {
    return true;
  }
  if (o2 === 0 && onSegment(startA, endA, endB)) {
    return true;
  }
  if (o3 === 0 && onSegment(startB, endB, startA)) {
    return true;
  }
  if (o4 === 0 && onSegment(startB, endB, endA)) {
    return true;
  }

  return false;
}

export function segmentIntersectsPolygon(start: Point, end: Point, polygon: Point[]): boolean {
  if (pointInPolygon(start, polygon) || pointInPolygon(end, polygon)) {
    return true;
  }

  for (let index = 0; index < polygon.length; index += 1) {
    const edgeStart = polygon[index];
    const edgeEnd = polygon[(index + 1) % polygon.length];
    if (segmentsIntersect(start, end, edgeStart, edgeEnd)) {
      return true;
    }
  }

  return false;
}
