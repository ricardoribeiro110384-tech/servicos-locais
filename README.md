# Serviços Locais

Catálogo para São Raimundo Nonato–PI. Requer Python 3.9 ou posterior.

## Abrir no computador

Extraia o ZIP, abra o terminal na pasta extraída e execute:

```sh
python3 app.py servir
```

Abra http://127.0.0.1:8000. Mantenha o terminal aberto. Os dados ficam em
`servicos.sqlite3`. Use a variável `SERVICOS_DB` para escolher outro caminho.

## Administrar

Abra outro terminal na mesma pasta. Liste os cadastros para localizar o ID.
Confirme pelo WhatsApp que o contato pertence ao prestador antes de aprovar.

```sh
python3 app.py listar
python3 app.py aprovar 1
python3 app.py ocultar 1
python3 app.py premium 1 --descricao "Instalação e manutenção" --foto "https://exemplo.com/foto.jpg"
python3 app.py avaliacao 1 5 "Chegou no horário combinado."
python3 app.py gratuito 1
```

Em avaliação, insira somente feedback real de clientes. O comando de plano pago
é manual. A opção de foto recebe uma URL HTTPS. Use uma URL vazia entre aspas
para tirar a foto. Na volta ao gratuito, o site deixa de servir os dados extras.

## Publicação

Esta versão roda localmente. Para receber cadastros públicos, prepare uma
implantação com HTTPS, armazenamento persistente, backup do SQLite e limitação
de requisições. O servidor Python incluído é destinado a uso local e testes.
A publicação dos perfis, a ativação do plano e as avaliações são administradas
pelo terminal. A cobrança e o envio de avaliações pelo público ficam para uma
etapa posterior.
