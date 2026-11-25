"""Conjunto pequeno para avaliar a recuperação por embeddings em português.

Escrito antes de ver qualquer resultado e não ajustado depois. É uma amostra mínima (14 trechos,
17 consultas): serve para comparar o modelo com o provedor falso lexical e para detectar regressão,
não para afirmar qualidade geral. Cada consulta tem no máximo um trecho relevante; os demais são
irrelevantes, e alguns são vizinhos do mesmo assunto (negativos difíceis).
"""

PASSAGES = {
    "locacao_prazo": "O contrato de locação residencial tem duração de trinta meses, com reajuste anual pelo IGP-M. "
    "Ao final do prazo, o locatário pode renovar mediante acordo com o proprietário.",
    "locacao_caucao": "Como garantia do aluguel, o inquilino depositou três meses de caução em conta poupança, que será "
    "devolvida ao fim do contrato se não houver débitos nem danos no imóvel.",
    "bolo": "Para o bolo de cenoura, bata no liquidificador as cenouras, os ovos e o óleo, misture com a farinha e o "
    "açúcar e asse por quarenta minutos em forno médio.",
    "wifi": "Para trocar a senha do wifi, entre no painel do roteador pelo endereço do gateway, abra a aba de segurança "
    "sem fio e defina uma nova chave de acesso.",
    "diabetes": "O diabetes tipo 2 exige acompanhamento da glicemia, alimentação equilibrada com pouco açúcar e atividade "
    "física regular, além de medicação prescrita pelo médico.",
    "sono": "Dormir pouco prejudica a memória e a concentração; adultos precisam de sete a nove horas de sono por noite, "
    "em um quarto escuro e silencioso.",
    "consumidor": "Pelo Código de Defesa do Consumidor, o cliente pode desistir de uma compra feita pela internet em até "
    "sete dias, e o fornecedor deve devolver o valor pago.",
    "selic": "A taxa Selic é a taxa básica de juros da economia; quando ela sobe, os financiamentos ficam mais caros e os "
    "investimentos de renda fixa passam a render mais.",
    "sql": "Para evitar consultas lentas no banco de dados, crie um índice nas colunas usadas em filtros e junções e "
    "analise o plano de execução da consulta.",
    "futebol": "O time venceu a final por dois a um, com gol de pênalti nos acréscimos, e conquistou o campeonato "
    "estadual pela décima vez.",
    "passaporte": "Para viajar ao exterior é preciso conferir a validade do passaporte, que deve ter pelo menos seis meses "
    "restantes, e verificar se o país exige visto.",
    "samambaia": "As samambaias preferem sombra e solo úmido; regue quando a superfície da terra estiver seca e evite sol "
    "direto nas folhas.",
    "solar": "Painéis solares transformam a luz do sol em eletricidade; o investimento se paga em alguns anos pela "
    "redução da conta de luz.",
    "relatorio_en": "The quarterly report shows that revenue grew eight percent, driven mainly by subscription renewals in "
    "the enterprise segment.",
}

# (consulta, id do trecho relevante, tipo). "parafrase": quase sem palavras em comum com o trecho.
# "palavras": reaproveita termos do trecho. "entre_idiomas": português procurando texto em inglês.
QUERIES = [
    ("por quanto tempo vale o aluguel do apartamento e quando o preço sobe?", "locacao_prazo", "parafrase"),
    ("o dinheiro que deixei como garantia volta pra mim?", "locacao_caucao", "parafrase"),
    ("como preparo uma sobremesa com raiz alaranjada?", "bolo", "parafrase"),
    ("mudar a chave da internet sem fio de casa", "wifi", "parafrase"),
    ("o que um paciente com açúcar alto no sangue deve fazer no dia a dia?", "diabetes", "parafrase"),
    ("quantas horas de descanso noturno um adulto precisa?", "sono", "parafrase"),
    ("posso devolver um produto comprado online?", "consumidor", "parafrase"),
    ("por que o financiamento fica caro quando o banco central aumenta os juros?", "selic", "parafrase"),
    ("como deixar uma consulta SQL mais rápida", "sql", "parafrase"),
    ("quem ganhou o campeonato e como foi o resultado?", "futebol", "parafrase"),
    ("documentos necessários para ir a outro país", "passaporte", "parafrase"),
    ("quanta luz e água uma planta de sombra precisa", "samambaia", "parafrase"),
    ("vale a pena instalar energia solar em casa?", "solar", "parafrase"),
    ("crescimento da receita no trimestre", "relatorio_en", "entre_idiomas"),
    ("contrato de locação residencial prazo", "locacao_prazo", "palavras"),
    ("senha do wifi roteador", "wifi", "palavras"),
]

# Sem resposta no corpus: serve para mostrar que a similaridade máxima não separa "achou" de "não achou".
OUT_OF_CORPUS = "previsão do tempo para a lua cheia em Marte"
