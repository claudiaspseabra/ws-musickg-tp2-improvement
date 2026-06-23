"""
SPIN rule definitions for the Music Knowledge Graph.

This module serves two TP2 purposes:
  - generate the deliverable SPIN-compatible Turtle file;
  - execute equivalent SPARQL UPDATE rules against the active RDF store.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterable


if __package__ in {None, ""}:
    # Allows: python music_kg_project/music_graph/spin_rules.py --output ...
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "music_kg_project" / "data" / "spin_rules.ttl"

TURTLE_PREFIXES = dedent(
    """\
    @prefix music: <http://musickg.org/ontology#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix sp: <http://spinrdf.org/sp#> .
    @prefix spin: <http://spinrdf.org/spin#> .
    """
)


@dataclass(frozen=True)
class SpinRule:
    resource: str
    target_class: str
    label: str
    comment: str
    construct: str
    update: str


RULES = [
    SpinRule(
        resource="InferPerformsFromAlbumTracksRule",
        target_class="Artist",
        label="Infer performs from albums and tracks",
        comment=(
            "Infers music:performs when an artist has an album and that album "
            "has a track."
        ),
        construct="""
        PREFIX music: <http://musickg.org/ontology#>
        CONSTRUCT {
          ?artist music:performs ?track .
        }
        WHERE {
          ?artist music:hasAlbum ?album .
          ?album music:hasTrack ?track .
        }
        """,
        update="""
        PREFIX music: <http://musickg.org/ontology#>
        INSERT {
          ?artist music:performs ?track .
        }
        WHERE {
          ?artist music:hasAlbum ?album .
          ?album music:hasTrack ?track .
          FILTER NOT EXISTS { ?artist music:performs ?track . }
        }
        """,
    ),
    SpinRule(
        resource="InferSymmetricSimilarToRule",
        target_class="Artist",
        label="Infer symmetric similarTo links",
        comment="Infers the reverse music:similarTo relation for artist similarity links.",
        construct="""
        PREFIX music: <http://musickg.org/ontology#>
        CONSTRUCT {
          ?right music:similarTo ?left .
        }
        WHERE {
          ?left music:similarTo ?right .
          FILTER (?left != ?right)
        }
        """,
        update="""
        PREFIX music: <http://musickg.org/ontology#>
        INSERT {
          ?right music:similarTo ?left .
        }
        WHERE {
          ?left music:similarTo ?right .
          FILTER (?left != ?right)
          FILTER NOT EXISTS { ?right music:similarTo ?left . }
        }
        """,
    ),
    SpinRule(
        resource="ClassifyHighEnergyTrackRule",
        target_class="Track",
        label="Classify high energy tracks",
        comment=(
            "Classifies tracks as music:HighEnergyTrack when their audio profile "
            "energy is at least 0.75."
        ),
        construct="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
          ?track a music:HighEnergyTrack .
          ?profile music:energyLevel "High" .
        }
        WHERE {
          ?track music:hasAudioProfile ?profile .
          ?profile music:energy ?energy .
          FILTER (xsd:decimal(?energy) >= 0.75)
        }
        """,
        update="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT {
          ?track a music:HighEnergyTrack .
          ?profile music:energyLevel "High" .
        }
        WHERE {
          ?track music:hasAudioProfile ?profile .
          ?profile music:energy ?energy .
          FILTER (xsd:decimal(?energy) >= 0.75)
        }
        """,
    ),
    SpinRule(
        resource="ClassifyPopularTrackRule",
        target_class="Track",
        label="Classify popular tracks",
        comment=(
            "Classifies tracks as music:PopularTrack when their popularity score "
            "is at least 70."
        ),
        construct="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
          ?track a music:PopularTrack .
          ?track music:popularityLevel "High" .
        }
        WHERE {
          ?track music:popularity ?popularity .
          FILTER (xsd:integer(?popularity) >= 70)
        }
        """,
        update="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT {
          ?track a music:PopularTrack .
          ?track music:popularityLevel "High" .
        }
        WHERE {
          ?track music:popularity ?popularity .
          FILTER (xsd:integer(?popularity) >= 70)
        }
        """,
    ),
    SpinRule(
        resource="ClassifyReleaseEraRule",
        target_class="Track",
        label="Classify release eras",
        comment=(
            "Classifies albums and tracks into broad release eras using album "
            "release years."
        ),
        construct="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
          ?album music:belongsToEra ?era .
          ?track music:belongsToEra ?era .
          ?track a ?trackClass .
        }
        WHERE {
          ?album music:hasTrack ?track ;
                 music:releaseYear ?year .
          BIND(xsd:integer(?year) AS ?releaseYear)
          BIND(
            IF(?releaseYear >= 2010, <http://musickg.org/era/Modern_Era>,
              IF(?releaseYear < 2000, <http://musickg.org/era/Classic_Era>, <http://musickg.org/era/Transition_Era>)
            ) AS ?era
          )
          BIND(
            IF(?releaseYear >= 2010, music:ModernTrack,
              IF(?releaseYear < 2000, music:ClassicTrack, music:Track)
            ) AS ?trackClass
          )
        }
        """,
        update="""
        PREFIX music: <http://musickg.org/ontology#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT {
          ?album music:belongsToEra ?era .
          ?track music:belongsToEra ?era .
          ?track a ?trackClass .
        }
        WHERE {
          ?album music:hasTrack ?track ;
                 music:releaseYear ?year .
          BIND(xsd:integer(?year) AS ?releaseYear)
          BIND(
            IF(?releaseYear >= 2010, <http://musickg.org/era/Modern_Era>,
              IF(?releaseYear < 2000, <http://musickg.org/era/Classic_Era>, <http://musickg.org/era/Transition_Era>)
            ) AS ?era
          )
          BIND(
            IF(?releaseYear >= 2010, music:ModernTrack,
              IF(?releaseYear < 2000, music:ClassicTrack, music:Track)
            ) AS ?trackClass
          )
        }
        """,
    ),
]


def _rule_text(text: str) -> str:
    return dedent(text).strip()


def _target_blocks() -> str:
    by_target: dict[str, list[str]] = {}
    for rule in RULES:
        by_target.setdefault(rule.target_class, []).append(rule.resource)

    blocks = []
    for target in sorted(by_target):
        resources = by_target[target]
        joined = ",\n        ".join(f"music:{resource}" for resource in resources)
        blocks.append(f"music:{target} spin:rule {joined} .")
    return "\n\n".join(blocks)


def _escape_turtle_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def build_spin_turtle() -> str:
    blocks = [TURTLE_PREFIXES.strip(), _target_blocks()]

    for rule in sorted(RULES, key=lambda item: item.resource):
        construct = _escape_turtle_string(_rule_text(rule.construct))
        blocks.append("\n".join(
            [
                f"music:{rule.resource} a sp:Construct,",
                "        spin:Rule ;",
                f'    rdfs:label "{rule.label}" ;',
                f'    sp:text """{construct}""" ;',
                f'    rdfs:comment "{rule.comment}" .',
            ]
        )
        )

    return "\n\n".join(blocks) + "\n"


def write_spin_rules(output_path: str | os.PathLike[str] = DEFAULT_OUTPUT) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_spin_turtle(), encoding="utf-8")
    return path


def execute_all_rules() -> None:
    """
    Execute SPARQL UPDATE equivalents of the SPIN rules against the active store.
    """
    from music_graph.rdf_store import store

    print("Starting SPIN inference rules...")
    for index, rule in enumerate(RULES, start=1):
        print(f"Executing Rule {index}: {rule.resource}...")
        ok = store.execute_sparql_update(_rule_text(rule.update))
        if not ok:
            raise RuntimeError(f"Failed to execute SPIN rule: {rule.resource}")
    print("All SPIN inference rules successfully executed.")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SPIN-compatible rules or execute their SPARQL UPDATE equivalents."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path for the generated SPIN Turtle file.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the rules against the active Django RDF store after writing the TTL file.",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    output = write_spin_rules(args.output)
    print(f"Wrote {output} ({len(RULES)} SPIN rules)")
    if args.execute:
        execute_all_rules()


if __name__ == "__main__":
    main()
