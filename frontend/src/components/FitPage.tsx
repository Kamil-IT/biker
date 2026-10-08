import { useState } from 'react'
import useFrameSize from '../hooks/useFrameSize'
import { FRAME_SIZE_LETTERS } from '../types'
import type { FitBikeType, FrameSizeResponse } from '../types'
import FrameSketch from './FrameSketch'

// The calculator's bike types, labelled as in the search form (SearchInput.tsx).
const BIKE_TYPES: { value: FitBikeType; label: string }[] = [
  { value: 'Road',              label: 'Szosowy' },
  { value: 'MTB',               label: 'Górski (MTB)' },
  { value: 'Gravel',            label: 'Gravel' },
  { value: 'City/Cross/Hybrid', label: 'Miejski / crossowy' },
  { value: 'Touring',           label: 'Trekkingowy' },
]

const fieldClass =
  'w-full pl-3.5 pr-12 py-2.5 bg-sand text-charcoal border border-border rounded-xl font-mono text-xl font-medium placeholder:text-muted-dark focus-visible:outline-none focus-visible:border-terra focus-visible:ring-2 focus-visible:ring-terra/40'

const labelClass = 'block mb-1.5 font-display font-semibold text-[17px] tracking-[0.02em] text-charcoal'

const boxClass = 'mt-4 px-4 py-3 rounded-xl border border-terra font-body text-[15px] leading-relaxed'

// 52.8 -> "52,8"
const decimal = (n: number) => n.toFixed(1).replace('.', ',')

interface FieldProps {
  id:          string
  label:       string
  value:       string
  placeholder: string
  describedBy?: string
  onChange:    (value: string) => void
}

function NumberField({ id, label, value, placeholder, describedBy, onChange }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        {label}<span className="sr-only"> w centymetrach</span>
      </label>
      <div className="relative">
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          maxLength={6}
          className={fieldClass}
          placeholder={placeholder}
          aria-describedby={describedBy}
          value={value}
          onChange={e => onChange(e.target.value)}
        />
        <span className="absolute right-3.5 top-1/2 -translate-y-1/2 font-mono text-sm text-ink pointer-events-none" aria-hidden="true">
          cm
        </span>
      </div>
    </div>
  )
}

// The numbers of an answer. Screen readers get one sentence (the visual block is hidden
// from them), so a new result is announced once instead of cell by cell.
function SizeResult({ result, pending }: { result: FrameSizeResponse; pending: boolean }) {
  const inches = result.unit === 'in'
  const range = `${decimal(result.range_min)}–${decimal(result.range_max)} ${inches ? 'cala' : 'cm'}`
  return (
    <div className={`transition-opacity duration-200 motion-reduce:transition-none ${pending ? 'opacity-60' : ''}`}>
      <p className="sr-only">
        Zalecany rozmiar ramy: {decimal(result.size)} {inches ? 'cala' : 'cm'}, litera {result.letter}. Zakres: {range}.
      </p>
      <div aria-hidden="true">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="font-display font-extrabold leading-[0.9] text-[length:clamp(4.5rem,20vw,7rem)]">
            {decimal(result.size)}
          </span>
          <span className="font-display font-semibold text-[28px] text-muted">{inches ? 'cala' : 'cm'}</span>
          <span className="ml-auto font-display font-bold text-4xl text-terra-light">{result.letter}</span>
        </div>
        <div className="grid grid-cols-5 gap-[3px] mt-5 mb-3">
          {FRAME_SIZE_LETTERS.map(letter => {
            const tone =
              letter === result.letter          ? 'bg-terra-dark text-parchment font-medium outline-2 outline-parchment/80' :
              result.letters.includes(letter)   ? 'bg-terra/35 text-parchment border border-terra' :
                                                  'bg-parchment/10 text-parchment/70'
            return (
              <div key={letter} className={`py-1.5 rounded text-center font-mono text-[13px] ${tone}`}>
                {letter}
              </div>
            )
          })}
        </div>
        <p className="font-body text-[15px] text-muted">
          Zakres: <strong className="font-medium text-parchment">{range}</strong>
        </p>
      </div>
      {result.confidence === 'medium' && (
        <p className="mt-3 font-body text-sm leading-relaxed text-parchment/75">
          Dla tego typu roweru wynik jest przybliżony: rozmiar zależy też od geometrii konkretnego modelu.
        </p>
      )}
      {result.measurement_warning && (
        <p className={boxClass}>
          Długość nogi wydaje się nietypowa przy tym wzroście. Zmierz ją jeszcze raz — od tego zależy wynik.
        </p>
      )}
    </div>
  )
}

// "Rower na Twoją miarę" tab (TODO-045): height, inseam and bike type in, the frame size
// the backend calculates (POST /v1/fit/frame-size) out, live as the fields are filled in.
// The page does no sizing maths of its own.
export default function FitPage() {
  const [height, setHeight] = useState('')
  const [inseam, setInseam] = useState('')
  const [bikeType, setBikeType] = useState<FitBikeType>('Road')
  const { state, result, message, retry } = useFrameSize(height, inseam, bikeType)

  const label = result ? `≈ ${decimal(result.size)} ${result.unit === 'cm' ? 'cm' : '″'}` : null

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 pb-20">
      <section className="pt-14 pb-8 md:pt-20 md:pb-10" aria-labelledby="fit-heading">
        <h1
          id="fit-heading"
          className="font-display font-bold leading-[0.92] tracking-tight text-charcoal text-[52px] sm:text-[68px] md:text-[80px] mb-4"
        >
          Jaki rozmiar<br />ramy dla Ciebie.
        </h1>
        <p className="font-body text-ink text-base md:text-[17px] leading-relaxed max-w-sm">
          Podaj wzrost i długość nogi, wybierz typ roweru. Rozmiar policzymy od razu.
        </p>
      </section>

      <form className="p-5 sm:p-6 bg-parchment border border-border rounded-[1.25rem]" onSubmit={e => e.preventDefault()} noValidate>
        <div className="grid gap-4 min-[480px]:grid-cols-2">
          <NumberField id="fit-height" label="Wzrost" value={height} placeholder="178" onChange={setHeight} />
          <NumberField
            id="fit-inseam"
            label="Długość nogi"
            value={inseam}
            placeholder="80"
            describedBy="fit-inseam-hint"
            onChange={setInseam}
          />
        </div>
        <p id="fit-inseam-hint" className="mt-3 font-body text-sm leading-relaxed text-ink">
          Długość nogi to odległość od krocza do podłogi, boso. Stań plecami do ściany, wsuń między nogi książkę jak siodło i zmierz do jej górnej krawędzi.
        </p>

        <fieldset className="mt-5 m-0 p-0 border-0 min-w-0">
          <legend className={`${labelClass} p-0`}>Typ roweru</legend>
          <div className="flex flex-wrap gap-2">
            {BIKE_TYPES.map(t => (
              <label key={t.value} className="relative cursor-pointer">
                <input
                  type="radio"
                  name="fit-bike-type"
                  value={t.value}
                  checked={bikeType === t.value}
                  onChange={() => setBikeType(t.value)}
                  className="peer sr-only"
                />
                <span className="block px-4 py-2 rounded-full border border-border bg-sand font-body text-[15px] text-charcoal transition-colors hover:border-ink peer-checked:bg-charcoal peer-checked:border-charcoal peer-checked:text-parchment peer-focus-visible:ring-2 peer-focus-visible:ring-terra peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-parchment">
                  {t.label}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </form>

      <section
        aria-live="polite"
        aria-busy={state === 'loading'}
        aria-label="Wynik"
        className="mt-6 overflow-hidden rounded-[1.25rem] bg-charcoal text-parchment"
      >
        <FrameSketch size={result?.size ?? null} unit={result?.unit ?? 'cm'} label={label} />
        <div className="px-5 sm:px-6 pb-6 min-h-24">
          {result && <SizeResult result={result} pending={state === 'loading'} />}
          {!result && state === 'idle' && (
            <p className="font-body text-muted leading-relaxed">
              Wpisz wzrost (140–210 cm) i długość nogi (60–110 cm), a pokażemy rozmiar.
            </p>
          )}
          {!result && state === 'loading' && <p className="font-body text-muted leading-relaxed">Liczę rozmiar…</p>}
          {state === 'invalid' && <p className="font-body text-[15px] leading-relaxed">{message}</p>}
          {state === 'error' && (
            <div>
              <p className="font-body text-[15px] leading-relaxed">{message}</p>
              <button
                type="button"
                onClick={retry}
                className="mt-3 px-5 py-2 rounded-xl border border-parchment/50 font-display font-bold text-base tracking-[0.04em] hover:bg-parchment hover:text-charcoal transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terra focus-visible:ring-offset-2 focus-visible:ring-offset-charcoal"
              >
                Spróbuj ponownie
              </button>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
