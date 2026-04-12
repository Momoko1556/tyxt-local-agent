import type { CollisionPolygon, Point, WalkGraph, WalkNode, WalkableZone } from './types';
import { distanceSquared, pointInPolygon, segmentIntersectsPolygon } from './geometry';

type WalkablePredicate = (point: Point) => boolean;

function findNearestNode(nodes: WalkNode[], target: Point): WalkNode {
  let nearest = nodes[0];
  let nearestDistance = distanceSquared(nearest, target);

  for (let index = 1; index < nodes.length; index += 1) {
    const node = nodes[index];
    const nextDistance = distanceSquared(node, target);
    if (nextDistance < nearestDistance) {
      nearest = node;
      nearestDistance = nextDistance;
    }
  }

  return nearest;
}

function edgeBlocked(fromNode: WalkNode, toNode: WalkNode, blockedPolygons: CollisionPolygon[]): boolean {
  for (const polygon of blockedPolygons) {
    if (segmentIntersectsPolygon(fromNode, toNode, polygon.points)) {
      return true;
    }
  }
  return false;
}

function edgeInsideWalkableZones(fromNode: WalkNode, toNode: WalkNode, walkableZones: WalkableZone[]): boolean {
  if (walkableZones.length === 0) {
    return true;
  }

  const samples = 8;
  for (let index = 0; index <= samples; index += 1) {
    const t = index / samples;
    const point = {
      x: fromNode.x + (toNode.x - fromNode.x) * t,
      y: fromNode.y + (toNode.y - fromNode.y) * t
    };

    const inside = walkableZones.some((zone) => zone.points.length >= 3 && pointInPolygon(point, zone.points));
    if (!inside) {
      return false;
    }
  }

  return true;
}

function edgeInsideWalkablePredicate(fromNode: WalkNode, toNode: WalkNode, predicate: WalkablePredicate): boolean {
  const samples = 8;
  for (let index = 0; index <= samples; index += 1) {
    const t = index / samples;
    const point = {
      x: fromNode.x + (toNode.x - fromNode.x) * t,
      y: fromNode.y + (toNode.y - fromNode.y) * t
    };
    if (!predicate(point)) {
      return false;
    }
  }
  return true;
}

function buildAdjacency(
  graph: WalkGraph,
  blockedPolygons: CollisionPolygon[],
  walkableZones: WalkableZone[],
  walkablePredicate?: WalkablePredicate
): Map<string, string[]> {
  const adjacency = new Map<string, string[]>();

  for (const node of graph.nodes) {
    adjacency.set(node.id, []);
  }

  const nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));

  for (const [fromId, toId] of graph.edges) {
    const fromNode = nodeMap.get(fromId);
    const toNode = nodeMap.get(toId);

    if (!fromNode || !toNode) {
      continue;
    }

    if (edgeBlocked(fromNode, toNode, blockedPolygons)) {
      continue;
    }

    const insideWalkable = walkablePredicate
      ? edgeInsideWalkablePredicate(fromNode, toNode, walkablePredicate)
      : edgeInsideWalkableZones(fromNode, toNode, walkableZones);
    if (!insideWalkable) {
      continue;
    }

    adjacency.get(fromId)?.push(toId);
    adjacency.get(toId)?.push(fromId);
  }

  return adjacency;
}

export function computeRoute(
  graph: WalkGraph,
  from: Point,
  to: Point,
  blockedPolygons: CollisionPolygon[] = [],
  walkableZones: WalkableZone[] = [],
  walkablePredicate?: WalkablePredicate
): WalkNode[] {
  const startNode = findNearestNode(graph.nodes, from);
  const endNode = findNearestNode(graph.nodes, to);

  if (startNode.id === endNode.id) {
    return [startNode];
  }

  const adjacency = buildAdjacency(graph, blockedPolygons, walkableZones, walkablePredicate);
  const queue: string[] = [startNode.id];
  const visited = new Set<string>([startNode.id]);
  const parent = new Map<string, string>();

  while (queue.length > 0) {
    const currentId = queue.shift();
    if (!currentId) {
      continue;
    }

    if (currentId === endNode.id) {
      break;
    }

    const neighbors = adjacency.get(currentId) ?? [];
    for (const neighborId of neighbors) {
      if (visited.has(neighborId)) {
        continue;
      }
      visited.add(neighborId);
      parent.set(neighborId, currentId);
      queue.push(neighborId);
    }
  }

  if (!visited.has(endNode.id)) {
    return [startNode];
  }

  const routeIds: string[] = [];
  let cursor: string | undefined = endNode.id;

  while (cursor) {
    routeIds.push(cursor);
    cursor = parent.get(cursor);
  }

  routeIds.reverse();
  const nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));

  return routeIds
    .map((nodeId) => nodeMap.get(nodeId))
    .filter((node): node is WalkNode => Boolean(node));
}
