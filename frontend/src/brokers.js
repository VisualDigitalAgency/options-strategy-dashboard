// Broker logos are official marks, used only to preview upcoming connections — not to claim a partnership.
import zerodha from './assets/brokers/zerodha.webp'
import upstox from './assets/brokers/upstox.webp'
import groww from './assets/brokers/groww.webp'
import angelone from './assets/brokers/angelone.webp'
import fyers from './assets/brokers/fyers.webp'
import icicidirect from './assets/brokers/icicidirect.webp'
import kotakneo from './assets/brokers/kotakneo.webp'
import fivepaisa from './assets/brokers/5paisa.webp'
// Flattrade/mStocks/Dhan (issue #38) have no backend adapter yet, so there's no live connection to
// preview against — just the "Coming soon" card, same as the other unconnected brokers above.
// Their marks are placeholder monograms, not the official logo; swap these for the real ones
// (matching the .webp treatment of the brokers above) once branded assets are on hand.
import flattrade from './assets/brokers/flattrade.svg'
import mstocks from './assets/brokers/mstocks.svg'
import dhan from './assets/brokers/dhan.svg'

export const BROKERS = [
  { id: 'zerodha', name: 'Zerodha', logo: zerodha },
  { id: 'upstox', name: 'Upstox', logo: upstox },
  { id: 'groww', name: 'Groww', logo: groww },
  { id: 'angelone', name: 'Angel One', logo: angelone },
  { id: 'fyers', name: 'Fyers', logo: fyers },
  { id: 'icicidirect', name: 'ICICI Direct', logo: icicidirect },
  { id: 'kotakneo', name: 'Kotak Neo', logo: kotakneo },
  { id: '5paisa', name: '5paisa', logo: fivepaisa },
  { id: 'flattrade', name: 'Flattrade', logo: flattrade },
  { id: 'mstocks', name: 'mStocks', logo: mstocks },
  { id: 'dhan', name: 'Dhan', logo: dhan },
]
