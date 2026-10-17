// Fixed coordinates for the 12 Online Boutique services, five columns wide so the graph stays
// legible in the ~600px centre pane at 1280px:
//   row 0                  frontend
//   row 1        checkout             recommendation
//   row 2  payment  email  cart  productcatalog  ad
//   row 3  currency currency-v2 redis-cart shipping
// Positions never move, so a topology change (currency → currency-v2 on day 24) reads as an edge
// moving while the nodes stay put.

export interface ServicePosition {
  x: number;
  y: number;
}

export const SERVICE_NODE_W = 168;
export const SERVICE_NODE_H = 52;
export const DEPLOY_NODE_W = 150;
export const DEPLOY_NODE_H = 30;

const COL = 196;
const ROW = 176;

export const SERVICE_POSITIONS: Record<string, ServicePosition> = {
  frontend: { x: 2 * COL, y: 0 },

  checkout: { x: 1 * COL, y: ROW },
  recommendation: { x: 3.5 * COL, y: ROW },

  payment: { x: 0, y: 2 * ROW },
  email: { x: 1 * COL, y: 2 * ROW },
  cart: { x: 2 * COL, y: 2 * ROW },
  productcatalog: { x: 3 * COL, y: 2 * ROW },
  ad: { x: 4 * COL, y: 2 * ROW },

  currency: { x: 0, y: 3 * ROW },
  'currency-v2': { x: 1 * COL, y: 3 * ROW },
  'redis-cart': { x: 2 * COL, y: 3 * ROW },
  shipping: { x: 3 * COL, y: 3 * ROW },
};

/** Registered position, or a grid slot below the known layout for services from other connectors. */
export function getServicePosition(name: string, fallbackIndex = 0): ServicePosition {
  if (SERVICE_POSITIONS[name]) return SERVICE_POSITIONS[name];
  return { x: (fallbackIndex % 5) * COL, y: (4 + Math.floor(fallbackIndex / 5)) * ROW };
}

/** Deploy pills stack under their service. */
export function getDeployPosition(servicePos: ServicePosition, stackIndex: number): ServicePosition {
  return {
    x: servicePos.x + (SERVICE_NODE_W - DEPLOY_NODE_W) / 2,
    y: servicePos.y + SERVICE_NODE_H + 16 + stackIndex * (DEPLOY_NODE_H + 6),
  };
}

// Two pills plus a "+n more" line fit between rows.
export const MAX_DEPLOYS_PER_SERVICE = 2;
