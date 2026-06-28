import os
import time
import requests
from rdflib import Graph, Namespace, Literal, URIRef
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib.namespace import RDF, OWL

# Namespace idêntico ao usado nas queries SPARQL do Django
MUSIC = Namespace("http://musickg.org/data/")
LOCAL_SPARQL = "http://localhost:7200/repositories/music-kg-tp2"

def get_local_artists(limit=100):
    """Obtém os artistas locais diretamente do GraphDB."""
    wrapper = SPARQLWrapper(LOCAL_SPARQL)
    wrapper.setQuery(f"""
        PREFIX music: <http://musickg.org/data/>
        SELECT ?artistUri ?name WHERE {{
            ?artistUri a music:Artist ;
                       music:artistName ?name .
        }} LIMIT {limit}
    """)
    wrapper.setReturnFormat(JSON)
    try:
        results = wrapper.query().convert()
        return [(r['artistUri']['value'], r['name']['value']) for r in results['results']['bindings']]
    except Exception as e:
        print(f"Erro ao ligar ao GraphDB: {e}")
        return []

def query_dbpedia_robust(artist_name):
    """Usa a DBpedia Lookup API e tenta sacar também o thumbnail da DBpedia."""
    url = f"https://lookup.dbpedia.org/api/search?query={artist_name.replace(' ', '+')}&format=JSON"
    headers = {"User-Agent": "MusicKG_UniversityProject/1.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10).json()
        docs = response.get('docs', [])
        if not docs: return None

        best_match = docs[0]
        resource_uri = best_match['resource'][0]
        abstract = best_match.get('comment', [''])[0]
        if not abstract: return None

        sparql = SPARQLWrapper("https://dbpedia.org/sparql")
        sparql.setQuery(f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX dbo: <http://dbpedia.org/ontology/>
            SELECT ?wikidata ?thumbnail WHERE {{
                OPTIONAL {{ 
                    <{resource_uri}> owl:sameAs ?wikidata . 
                    FILTER(STRSTARTS(STR(?wikidata), "http://www.wikidata.org/entity/")) 
                }}
                OPTIONAL {{ <{resource_uri}> dbo:thumbnail ?thumbnail . }}
            }} LIMIT 1
        """)
        sparql.setReturnFormat(JSON)

        wikidata_uri = None
        thumbnail_uri = None
        try:
            wd_res = sparql.query().convert()['results']['bindings']
            if wd_res:
                wikidata_uri = wd_res[0].get('wikidata', {}).get('value')
                thumbnail_uri = wd_res[0].get('thumbnail', {}).get('value')
        except Exception:
            pass

        return {
            'abstract': abstract,
            'wikidata': wikidata_uri,
            'thumbnail': thumbnail_uri
        }
    except Exception:
        pass
    return None

def query_wikidata(wikidata_uri):
    """Consulta a Wikidata, mas faz a imagem OPTIONAL para não falhar a query toda."""
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
    wd_id = wikidata_uri.split("/")[-1]
    sparql.setQuery(f"""
        SELECT ?image ?countryLabel WHERE {{
            wd:{wd_id} wdt:P31 ?any .
            OPTIONAL {{ wd:{wd_id} wdt:P18 ?image . }}
            OPTIONAL {{
                wd:{wd_id} wdt:P27|wdt:P19|wdt:P495 ?country .
                ?country rdfs:label ?countryLabel .
                FILTER(lang(?countryLabel) = "en")
            }}
        }} LIMIT 1
    """)
    sparql.setReturnFormat(JSON)
    sparql.agent = "MusicKG_UniversityProject/1.0"
    try:
        res = sparql.query().convert()['results']['bindings']
        if res:
            return {
                'image': res[0].get('image', {}).get('value'),
                'country': res[0].get('countryLabel', {}).get('value')
            }
    except Exception:
        pass
    return None

def main():
    print("Iniciando Extração Avançada de Dados Externos (Método Lookup API)...")
    artists = get_local_artists(limit=100)

    if not artists:
        print("Erro: Nenhum artista carregado. Verifica o GraphDB.")
        return

    g = Graph()
    g.bind("music", MUSIC)
    g.bind("owl", OWL)

    count = 0
    for uri, name in artists:
        print(f"A pesquisar: {name} ...", end=" ")
        db_data = query_dbpedia_robust(name)

        if db_data:
            artist_ref = URIRef(uri)
            g.add((artist_ref, MUSIC.dbpediaAbstract, Literal(db_data['abstract'], lang="en")))

            if db_data.get('thumbnail'):
                g.add((artist_ref, MUSIC.imageUrl, URIRef(db_data['thumbnail'])))

            if db_data.get('wikidata'):
                g.add((artist_ref, OWL.sameAs, URIRef(db_data['wikidata'])))
                wd_data = query_wikidata(db_data['wikidata'])

                if wd_data:
                    if wd_data.get('image'):
                        g.add((artist_ref, MUSIC.imageUrl, URIRef(wd_data['image'])))
                    if wd_data.get('country'):
                        g.add((artist_ref, MUSIC.hometown, Literal(wd_data['country'])))

            count += 1
            print("✅ Encontrado!")
        else:
            print("❌ Falhou.")

        time.sleep(0.5)

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "enrichment.ttl")
    g.serialize(destination=out_path, format="turtle")
    print(f"\nEnriquecimento concluído! Dados adicionados a {count} artistas.")
    print(f"Ficheiro guardado em: {out_path}")

if __name__ == "__main__":
    main()