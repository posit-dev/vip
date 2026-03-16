@connect
Feature: Connect content deployment
  As a Posit Team administrator
  I want to verify that content can be deployed and executed
  So that I know the Connect publishing pipeline is functional

  Scenario: Deploy and execute a Quarto document
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-quarto-test"
    And I upload and deploy a minimal Quarto bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute a Plumber API
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-plumber-test"
    And I upload and deploy a minimal Plumber bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute a Shiny application
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-shiny-test"
    And I upload and deploy a minimal Shiny bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute a Dash application
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-dash-test"
    And I upload and deploy a minimal Dash bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute an R Markdown document
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-rmarkdown-test"
    And I upload and deploy a minimal R Markdown bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute a Jupyter Notebook
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-jupyter-test"
    And I upload and deploy a minimal Jupyter Notebook bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content

  Scenario: Deploy and execute a FastAPI application
    Given Connect is accessible at the configured URL
    When I create a VIP test content item named "vip-fastapi-test"
    And I upload and deploy a minimal FastAPI bundle
    And I wait for the deployment to complete
    Then the content is accessible via HTTP
    And the content renders expected output
    And I clean up the test content
