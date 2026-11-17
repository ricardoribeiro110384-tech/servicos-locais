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

## Publicação na Vercel com Neon

O catálogo público usa PostgreSQL. A versão local continua usando SQLite.

1. Execute `schema.sql` no projeto dedicado do Neon.
2. Configure `DATABASE_URL` como variável sensível de produção na Vercel.
3. Publique os arquivos na Vercel. O HTML é servido na raiz e as funções
   Python atendem `/api/catalogo` e `/api/cadastro`.

Confira o contato e use o editor SQL do Neon para moderar os cadastros online.
Substitua o ID de exemplo pelo ID do cadastro conferido.

```sql
SELECT id, category, name, phone, status FROM providers WHERE status = 'pending';
UPDATE providers SET status = 'active' WHERE id = 123 AND status = 'pending';
```

A ativação de plano pago e a edição dos dados premium são manuais, no banco.
Os comandos administrativos do Python atuam somente no banco local.

### Painel administrativo

Acesse `/admin` e entre com o usuário `admin`. Se nunca trocou a senha
no painel, use o valor de `ADMIN_PASSWORD` da publicação de produção.

Para trocar a senha, abra **Alterar senha do administrador**, informe a senha
atual e escolha uma nova de pelo menos 15 caracteres. Após salvar, entre de
novo com a nova senha. A senha escolhida no painel é armazenada como hash.

Se esquecer a senha, defina um valor novo e exclusivo em `ADMIN_PASSWORD`
na Vercel e faça uma nova publicação de produção. Use esse valor para entrar
e, depois, escolha uma senha pelo painel.
