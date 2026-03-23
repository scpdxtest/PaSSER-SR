import {APIClient} from '@wharfkit/antelope'
import configuration from './configuration.json';

export async function checkBCEndpoint() {
    const epoints = configuration.passer.BCEndPoints.map(item => item.url);
    const res = [];
    for (let i = 0; i < epoints.length; i++) {
        const ch = new APIClient({url: epoints[i]});
        try {
            const res = await ch.v1.chain.get_info();
            return epoints[i];
        } catch (err) {
            console.log("chain info error", err);
        }
    }
}

export async function checkIPFSEndpoint() {
    return configuration.passer.IPFSEndPoints[1];
}