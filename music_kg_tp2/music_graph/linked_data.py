import os
import time
import requests
import urllib3
from rdflib import Graph, Namespace, Literal, URIRef
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib.namespace import RDF, OWL

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MUSIC = Namespace("http://musickg.org/data/")
LOCAL_SPARQL = "http://localhost:7200/repositories/music-kg-tp2"


def get_local_artists(limit=10000):
    wrapper = SPARQLWrapper(LOCAL_SPARQL)
    wrapper.setQuery(
        f"PREFIX music: <http://musickg.org/data/> SELECT ?artistUri ?name WHERE {{ ?artistUri a music:Artist ; music:artistName ?name . }} LIMIT {limit}")
    wrapper.setReturnFormat(JSON)
    try:
        results = wrapper.query().convert()
        return [(r['artistUri']['value'], r['name']['value']) for r in results['results']['bindings']]
    except Exception:
        return []


def query_dbpedia_robust(artist_name):
    url = f"https://lookup.dbpedia.org/api/search?query={artist_name.replace(' ', '+')}&format=JSON"
    headers = {"User-Agent": "MusicKG_UniversityProject/1.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10, verify=False).json()
        if not response.get('docs'): return None

        best_match = response['docs'][0]
        resource_uri = best_match['resource'][0]
        short_abstract = best_match.get('comment', [''])[0]

        sparql_query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX dbo: <http://dbpedia.org/ontology/>
            SELECT ?abstract ?wikidata ?thumbnail WHERE {{
                OPTIONAL {{ <{resource_uri}> dbo:abstract ?abstract . FILTER(lang(?abstract) = "en") }}
                OPTIONAL {{ <{resource_uri}> owl:sameAs ?wikidata . FILTER(STRSTARTS(STR(?wikidata), "http://www.wikidata.org/entity/")) }}
                OPTIONAL {{ <{resource_uri}> dbo:thumbnail ?thumbnail . }}
            }} LIMIT 1
        """

        r_db = requests.get("https://dbpedia.org/sparql", params={"query": sparql_query, "format": "json"},
                            headers=headers, timeout=10, verify=False)

        final_abstract = short_abstract
        wikidata_uri = None
        thumbnail_uri = None

        if r_db.status_code == 200:
            bindings = r_db.json().get('results', {}).get('bindings', [])
            if bindings:
                if 'abstract' in bindings[0]: final_abstract = bindings[0]['abstract']['value']
                if 'wikidata' in bindings[0]: wikidata_uri = bindings[0]['wikidata']['value']
                if 'thumbnail' in bindings[0]: thumbnail_uri = bindings[0]['thumbnail']['value']

        return {
            'abstract': final_abstract,
            'wikidata': wikidata_uri,
            'thumbnail': thumbnail_uri
        }
    except Exception as e:
        pass
    return None


def query_wikidata(wikidata_uri):
    wd_id = wikidata_uri.split("/")[-1]

    sparql_query = f"""
        SELECT ?image ?countryLabel WHERE {{
            OPTIONAL {{ wd:{wd_id} wdt:P18 ?image . }}
            OPTIONAL {{
                wd:{wd_id} wdt:P27|(wdt:P19/wdt:P17)|wdt:P495 ?country .
                ?country rdfs:label ?countryLabel .
                FILTER(lang(?countryLabel) = "en")
            }}
        }} LIMIT 1
    """

    headers = {
        "User-Agent": "MusicKG_UniversityProject/1.0 (mailto:student@ua.pt)",
        "Accept": "application/sparql-results+json"
    }
    try:
        r_wd = requests.get("https://query.wikidata.org/sparql", params={"query": sparql_query}, headers=headers,
                            timeout=10, verify=False)
        if r_wd.status_code == 200:
            bindings = r_wd.json().get('results', {}).get('bindings', [])
            if bindings:
                return {
                    'image': bindings[0].get('image', {}).get('value'),
                    'country': bindings[0].get('countryLabel', {}).get('value')
                }
    except Exception as e:
        pass
    return None


def main():
    print("Starting Extraction with SSL Bypass...")
    artists = get_local_artists(limit=10000)

    if not artists:
        print("Error: No artists loaded.")
        return

    g = Graph()
    g.bind("music", MUSIC)
    g.bind("owl", OWL)

    count = 0
    for uri, name in artists:
        print(f"Searching: {name} ...", end=" ")
        db_data = query_dbpedia_robust(name)

        if db_data:
            artist_ref = URIRef(uri)
            raw_abstract = db_data.get('abstract', '')
            if raw_abstract and ". " in raw_abstract:
                first_sentence = raw_abstract.split(". ")[0] + "."
            else:
                first_sentence = raw_abstract

            g.add((artist_ref, MUSIC.dbpediaAbstract, Literal(first_sentence, lang="en")))

            if db_data.get('thumbnail'):
                g.add((artist_ref, MUSIC.imageUrl, URIRef(db_data['thumbnail'])))

            if db_data.get('wikidata'):
                g.add((artist_ref, OWL.sameAs, URIRef(db_data['wikidata'])))
                wd_data = query_wikidata(db_data['wikidata'])

                if wd_data:
                    if wd_data.get('image'):
                        g.set((artist_ref, MUSIC.imageUrl, URIRef(wd_data['image'])))
                    if wd_data.get('country'):
                        g.add((artist_ref, MUSIC.hometown, Literal(wd_data['country'])))

            count += 1
            print("Found!")
        else:
            print("❌ Failed.")

        time.sleep(1.0)

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "enrichment.ttl")
    g.serialize(destination=out_path, format="turtle")
    print(f"\nCompleted! File saved to: {out_path}")


if __name__ == "__main__":
    main()
