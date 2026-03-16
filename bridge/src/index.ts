import { BridgeServer } from './server.js';
import { bridgeLog } from './logger.js';

const PORT = parseInt(process.env.REACHY_BRIDGE_PORT || process.env.BRIDGE_PORT || '18790', 10);

bridgeLog.info('main', 'nanobot Edge Bridge starting');

const server = new BridgeServer(PORT);
server.start();

process.on('SIGINT', () => { server.stop(); process.exit(0); });
process.on('SIGTERM', () => { server.stop(); process.exit(0); });
